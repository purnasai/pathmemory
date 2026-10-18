
**ablation**

| mode | success | replay reached goal | model calls | input tok | output tok | est. $ | browser steps | replayed | episode s | reset s | route hops | recoveries | failed checks | wrong-target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| graph | 5/5 | 0/5 | 8.4 | 24,859 | 656 | 0.0028 | 7.4 | 0.0 | 36.7 | 8.3 | 3.0 | 0.0 | 1.0 | 0.0 |

**broken**

| mode | success | replay reached goal | model calls | input tok | output tok | est. $ | browser steps | replayed | episode s | reset s | route hops | recoveries | failed checks | wrong-target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | 5/5 | 0/5 | 7.0 | 20,628 | 546 | 0.0023 | 7.0 | 0.0 | 32.8 | 8.1 | 0.0 | 0.0 | 0.0 | 0.0 |
| flat | 5/5 | 0/5 | 7.6 | 25,389 | 618 | 0.0028 | 7.6 | 0.0 | 34.7 | 8.8 | 0.0 | 0.0 | 0.0 | 0.0 |
| flatreplay | 5/5 | 0/5 | 8.4 | 23,718 | 631 | 0.0027 | 7.4 | 0.0 | 34.7 | 7.3 | 3.0 | 0.0 | 1.0 | 0.0 |
| graph | 5/5 | 5/5 | 6.0 | 14,986 | 472 | 0.0017 | 9.0 | 4.0 | 33.5 | 8.5 | 4.0 | 1.0 | 1.0 | 0.0 |

**broken_flat_pinned**

| mode | success | replay reached goal | model calls | input tok | output tok | est. $ | browser steps | replayed | episode s | reset s | route hops | recoveries | failed checks | wrong-target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| flat | 5/5 | 0/5 | 7.8 | 26,549 | 650 | 0.0030 | 7.6 | 0.0 | 36.2 | 8.4 | 0.0 | 0.0 | 0.0 | 0.0 |

**normal**

| mode | success | replay reached goal | model calls | input tok | output tok | est. $ | browser steps | replayed | episode s | reset s | route hops | recoveries | failed checks | wrong-target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | 5/5 | 0/5 | 8.0 | 22,779 | 565 | 0.0026 | 8.0 | 0.0 | 38.2 | 9.6 | 0.0 | 0.0 | 0.0 | 0.0 |
| flat | 5/5 | 0/5 | 8.2 | 26,359 | 572 | 0.0029 | 8.0 | 0.0 | 36.8 | 8.8 | 0.0 | 0.0 | 0.0 | 0.0 |
| flatreplay | 5/5 | 5/5 | 6.0 | 14,788 | 466 | 0.0017 | 8.0 | 3.0 | 32.1 | 8.7 | 3.0 | 0.0 | 0.0 | 0.0 |
| graph | 5/5 | 5/5 | 6.0 | 14,926 | 464 | 0.0017 | 8.0 | 3.0 | 31.7 | 9.1 | 3.0 | 0.0 | 0.0 | 0.0 |
