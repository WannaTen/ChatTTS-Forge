from fastapi import HTTPException

from pydantic import BaseModel


from modules import refiner

from modules.api import utils as api_utils
from modules.api.Api import APIManager


class RefineTextRequest(BaseModel):
    text: str
    prompt: str = "[oral_2][laugh_0][break_6]"
    seed: int = -1
    top_P: float = 0.7
    top_K: int = 20
    temperature: float = 0.7
    repetition_penalty: float = 1.0
    max_new_token: int = 384


async def refiner_prompt_post(request: RefineTextRequest):
    """
    This endpoint receives a prompt and returns the refined result
    """

    try:
        refined_text = refiner.refine_text(
            text=request.text,
            prompt=request.prompt,
            seed=request.seed,
            top_P=request.top_P,
            top_K=request.top_K,
            temperature=request.temperature,
            repetition_penalty=request.repetition_penalty,
            max_new_token=request.max_new_token,
        )
        return {"message": "ok", "data": refined_text}

    except Exception as e:
        import logging

        logging.exception(e)

        if isinstance(e, HTTPException):
            raise e
        else:
            raise HTTPException(status_code=500, detail=str(e))


def setup(api_manager: APIManager):
    api_manager.post("/v1/prompt/refine", response_model=api_utils.BaseResponse)(
        refiner_prompt_post
    )
