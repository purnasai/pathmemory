"""Run PathMemory tasks on the local Gitea with an AgentLab agent.

    uv run python -m pathmemory.run profile-3 issues-5 --no-reset
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from agentlab.agents.generic_agent.agent_configs import FLAGS_CUSTOM
from bgym import HighLevelActionSetArgs
from agentlab.agents.generic_agent.generic_agent import GenericAgentArgs
from agentlab.experiments.loop import EnvArgs, ExpArgs
from agentlab.llm.chat_api import OpenAIModelArgs

from pathmemory.config import settings
from pathmemory.site import seed
from pathmemory.site.tasks import TASKS_BY_ID, register_all

RESULTS = settings.root / "results"


def base_agent_args() -> GenericAgentArgs:
    model = OpenAIModelArgs(
        model_name=settings.openai_model,
        max_total_tokens=128_000,
        max_input_tokens=100_000,
        max_new_tokens=8_000,
        temperature=1.0,  # gpt-6-luna only accepts the default
    )
    # FLAGS_CUSTOM only allows bid actions; tasks need send_msg_to_user (chat) and goto/back (nav).
    action = replace(FLAGS_CUSTOM.action, action_set=HighLevelActionSetArgs(subsets=["chat", "bid", "nav"], multiaction=False))
    flags = replace(FLAGS_CUSTOM, action=action, use_hints=False, be_cautious=False)
    return GenericAgentArgs(chat_model_args=model, flags=flags)


def run_task(task_id: str, agent_args, out_dir: Path, max_steps=15, reset=True, ui_break=None) -> dict:
    if reset and TASKS_BY_ID[task_id].kind == "mutate":
        seed.reset()
    env_args = EnvArgs(task_name=f"pathmemory.{task_id}", task_seed=0, max_steps=max_steps, headless=True,
                       task_kwargs={"ui_break": ui_break} if ui_break else None)
    exp = ExpArgs(agent_args=agent_args, env_args=env_args)
    exp.prepare(out_dir)
    exp.run()
    summary = json.loads((Path(exp.exp_dir) / "summary_info.json").read_text())
    return {
        "task": task_id,
        "success": summary.get("cum_reward", 0) > 0,
        "steps": summary.get("n_steps"),
        "err": summary.get("err_msg"),
        "input_tokens": summary.get("stats.cum_input_tokens"),
        "output_tokens": summary.get("stats.cum_output_tokens"),
        "exp_dir": str(exp.exp_dir),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tasks", nargs="+")
    p.add_argument("--no-reset", action="store_true")
    p.add_argument("--max-steps", type=int, default=15)
    a = p.parse_args()
    register_all()
    out = RESULTS / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    for t in a.tasks:
        r = run_task(t, base_agent_args(), out, a.max_steps, reset=not a.no_reset)
        print(json.dumps(r))


if __name__ == "__main__":
    main()
