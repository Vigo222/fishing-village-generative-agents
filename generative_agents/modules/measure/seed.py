"""自然相遇模式的消息播种说明。"""

import json

SEED_KEYS = {"step", "source", "listener", "message"}


def load_seed_message(path):
    """自然相遇的播种说明:第几步、谁(场外消息源)告诉哪位居民、消息原文。

    事实槽(答案表)不在这里,只交给 score.py。
    """
    with open(path, "r", encoding="utf-8") as f:
        seed = json.load(f)
    if set(seed) != SEED_KEYS:
        raise ValueError(
            "seed message keys must be exactly {}, got {}".format(sorted(SEED_KEYS), sorted(seed))
        )
    if not isinstance(seed["step"], int) or seed["step"] < 1:
        raise ValueError("seed message step must be an integer >= 1")
    return seed
