"""Embed the CLIP text prompts of `tags.py` once → `clip_prompts.npy` (committed).

Needs the ML extra plus `tokenizers`, and the CLIP ViT-B/32 text tower and
tokenizer from the same commit as the vision model (models.py):

    base=https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/d15189d7028b43f1d3e65039190477f6af591c2a
    curl -LO $base/onnx/text_model.onnx; curl -LO $base/tokenizer.json
    uv run --with tokenizers python -m \\
        virtubooth.extensions.wall.enrich.analyzers.make_clip_prompts text_model.onnx tokenizer.json

Rerun after changing PROMPTS. The output: float32 [len(PROMPTS), 512], L2-normalised.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from ._ml import onnx_session
from .tags import PROMPTS, PROMPTS_FILE


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("text_model", help="onnx/text_model.onnx")
    p.add_argument("tokenizer", help="tokenizer.json")
    args = p.parse_args(argv)
    from tokenizers import Tokenizer  # only for this script

    tok = Tokenizer.from_file(args.tokenizer)
    session = onnx_session(args.text_model)
    rows = []
    for _group, _key, text in PROMPTS:
        ids = np.array([tok.encode(text).ids], dtype=np.int64)
        emb = np.asarray(session.run(["text_embeds"], {"input_ids": ids})[0][0], dtype=np.float32)
        rows.append(emb / np.linalg.norm(emb))
    np.save(PROMPTS_FILE, np.stack(rows).astype(np.float32))
    print(f"wrote {PROMPTS_FILE} ({len(rows)} prompts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
