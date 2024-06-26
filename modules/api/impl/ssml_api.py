from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from modules.api.Api import APIManager
from modules.api.impl.handler.SSMLHandler import SSMLHandler
from modules.api.impl.model.audio_model import AdjustConfig, AudioFormat
from modules.api.impl.model.chattts_model import InferConfig
from modules.api.impl.model.enhancer_model import EnhancerConfig


class SSMLRequest(BaseModel):
    ssml: str
    format: AudioFormat = "mp3"

    # NOTE: 🤔 也许这个值应该配置成系统变量？ 传进来有点奇怪
    batch_size: int = 4

    # end of sentence
    eos: str = "[uv_break]"

    spliter_thr: int = 100

    enhancer: EnhancerConfig = EnhancerConfig()
    adjuster: AdjustConfig = AdjustConfig()


async def synthesize_ssml_api(
    request: SSMLRequest = Body(
        ..., description="JSON body with SSML string and format"
    )
):
    try:
        ssml = request.ssml
        format = request.format.lower()
        batch_size = request.batch_size
        eos = request.eos
        spliter_thr = request.spliter_thr
        enhancer = request.enhancer
        adjuster = request.adjuster

        if batch_size < 1:
            raise HTTPException(
                status_code=400, detail="Batch size must be greater than 0."
            )

        if spliter_thr < 50:
            raise HTTPException(
                status_code=400, detail="Spliter threshold must be greater than 50."
            )

        if not ssml or ssml == "":
            raise HTTPException(status_code=400, detail="SSML content is required.")

        if format not in ["mp3", "wav"]:
            raise HTTPException(
                status_code=400, detail="Format must be 'mp3' or 'wav'."
            )

        infer_config = InferConfig(
            batch_size=batch_size,
            spliter_threshold=spliter_thr,
            eos=eos,
        )
        adjust_config = adjuster
        enhancer_config = enhancer

        handler = SSMLHandler(
            ssml_content=ssml,
            infer_config=infer_config,
            adjust_config=adjust_config,
            enhancer_config=enhancer_config,
        )

        buffer = handler.enqueue_to_buffer(format=request.format)

        mime_type = f"audio/{format}"
        if format == AudioFormat.mp3:
            mime_type = "audio/mpeg"
        return StreamingResponse(buffer, media_type=mime_type)

    except Exception as e:
        import logging

        logging.exception(e)

        if isinstance(e, HTTPException):
            raise e
        else:
            raise HTTPException(status_code=500, detail=str(e))


def setup(api_manager: APIManager):
    api_manager.post("/v1/ssml", response_class=FileResponse)(synthesize_ssml_api)
