import json


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(path, items):
    payload = {it.key: {"price": it.price, "flags": it.flags} for it in items}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def diff(items, prev):
    new_items, still_items = [], []
    for it in items:
        if it.key in prev:
            still_items.append((it, prev[it.key].get("price")))
        else:
            new_items.append(it)
    return new_items, still_items
