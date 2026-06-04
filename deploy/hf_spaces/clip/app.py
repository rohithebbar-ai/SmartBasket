import base64
import io
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("CLIP_SERVICE_API_KEY", "")

_model = None
_preprocess = None
_tokenize = None


def _load_model():
    import torch
    import open_clip

    global _model, _preprocess, _tokenize
    logger.info("Loading CLIP model ViT-B-32...")
    _model, _, _preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai"
    )
    _tokenize = open_clip.get_tokenizer("ViT-B-32")
    _model.eval()
    logger.info("CLIP model loaded successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_model()
    yield


app = FastAPI(title="CLIP Visual Search Service", lifespan=lifespan)


class ClassifyRequest(BaseModel):
    image_b64: str
    candidates: dict[str, list[str]]


class ClassifyResponse(BaseModel):
    top: dict[str, Optional[str]]
    scores: dict[str, dict[str, float]]


@app.get("/health")
def health():
    return {"status": "ok", "model": "ViT-B-32"}


@app.post("/classify", response_model=ClassifyResponse)
def classify(
    req: ClassifyRequest,
    x_api_key: str = Header(default=""),
):
    try:
        import torch

        if API_KEY and x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

        # Decode image
        image_data = req.image_b64
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        image_input = _preprocess(image).unsqueeze(0)

        top: dict[str, Optional[str]] = {}
        scores: dict[str, dict[str, float]] = {}

        with torch.no_grad():
            image_features = _model.encode_image(image_input)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

            for attr, labels in req.candidates.items():
                if not labels:
                    continue

                texts = _tokenize(labels)
                text_features = _model.encode_text(texts)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)

                similarity = (image_features @ text_features.T).squeeze(0)
                probs = similarity.softmax(dim=0).numpy()

                label_scores = {label: float(prob) for label, prob in zip(labels, probs)}
                scores[attr] = label_scores

                best_label = max(label_scores, key=label_scores.get)
                # Always return top-1 — no threshold.
                # With large candidate sets (e.g. 42 colour names) softmax is spread thin
                # and absolute scores stay near uniform, but CLIP's relative ranking is
                # still meaningful. A threshold here just collapses everything to the
                # fallback query "clothing".
                top[attr] = best_label

        return ClassifyResponse(top=top, scores=scores)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error during /classify: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
