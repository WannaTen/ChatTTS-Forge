from typing import Any, Generator, Union

import numpy as np

from modules.core.models.AudioReshaper import AudioReshaper
from modules.core.models.TTSModel import TTSModel
from modules.core.models.zoo.ChatTTS import ChatTTS, load_chat_tts, unload_chat_tts
from modules.core.models.zoo.ChatTTSInfer import ChatTTSInfer
from modules.core.pipeline.dcls import TTSPipelineContext
from modules.core.pipeline.pipeline import TTSSegment
from modules.core.pipeline.processor import NP_AUDIO
from modules.core.spk.TTSSpeaker import TTSSpeaker
from modules.utils import audio_utils
from modules.utils.SeedContext import SeedContext


class ChatTTSModel(TTSModel):
    model_id = "chat-tts"

    @staticmethod
    def create_speaker_from_seed(seed: int):
        chat = load_chat_tts()
        with SeedContext(seed):
            token = chat._sample_random_speaker().float()
            spk = TTSSpeaker.empty()
            spk.set_token(tokens=[token], model_id=ChatTTSModel.model_id)
            spk.set_name(f"spk[seed={seed}]")
            return spk

    def __init__(self) -> None:
        super().__init__("chat-tts")
        self.chat: ChatTTS.Chat = None

    def is_loaded(self) -> bool:
        return self.chat is not None

    def load(self) -> "ChatTTS.Chat":
        self.chat = load_chat_tts()
        return self.chat

    def unload(self, context: TTSPipelineContext = None) -> None:
        unload_chat_tts(self.chat)
        self.chat = None

    def encode(self, text: str) -> list[int]:
        self.load()
        tokenizer = self.chat.tokenizer._tokenizer
        return tokenizer.encode(text)

    def decode(self, ids: list[int]) -> str:
        self.load()
        tokenizer = self.chat.tokenizer._tokenizer
        return tokenizer.decode(ids)

    def generate_batch(
        self, segments: list[TTSSegment], context: TTSPipelineContext
    ) -> list[NP_AUDIO]:
        return self.generate_batch_base(segments, context, stream=False)

    def generate_batch_stream(
        self, segments: list[TTSSegment], context: TTSPipelineContext
    ) -> Generator[list[NP_AUDIO], Any, None]:
        return self.generate_batch_base(segments, context, stream=True)

    def get_infer(self, context: TTSPipelineContext):
        return ChatTTSInfer(self.load())

    current_infer: ChatTTSInfer = None

    def interrupt(self, context: TTSPipelineContext = None) -> None:
        self.current_infer.interrupt()

    def get_ref_wav(self, segment: TTSSegment):
        spk = segment.spk
        if spk is None:
            return None, None
        emotion = segment.emotion
        ref_data = spk.get_ref(lambda x: x.emotion == emotion)
        if ref_data is None:
            return None, None
        wav = audio_utils.bytes_to_librosa_array(
            audio_bytes=ref_data.wav, sample_rate=ref_data.wav_sr
        )
        _, wav = AudioReshaper.normalize_audio(
            audio=(ref_data.wav_sr, wav),
            # 调整采样率到 24kHz
            target_sr=24000,
        )
        text = ref_data.text
        return wav, text

    def generate_batch_base(
        self, segments: list[TTSSegment], context: TTSPipelineContext, stream=False
    ) -> Union[list[NP_AUDIO], Generator[list[NP_AUDIO], Any, None]]:
        cached = self.get_cache(segments=segments, context=context)
        if cached is not None:
            if not stream:
                return cached

            def _gen():
                yield cached

            return _gen()

        infer = self.get_infer(context)
        self.current_infer = infer

        texts = [segment.text for segment in segments]

        seg0 = segments[0]
        spk_emb = self.get_spk_emb(segment=seg0, context=context) if seg0.spk else None
        spk_wav, txt_smp = self.get_ref_wav(seg0)
        spk_smp = infer._sample_audio_speaker(spk_wav) if spk_wav is not None else None
        top_P = seg0.top_p
        top_K = seg0.top_k
        temperature = seg0.temperature
        # repetition_penalty = seg0.repetition_penalty
        # max_new_token = seg0.max_new_token
        prompt1 = seg0.prompt1
        prompt2 = seg0.prompt2
        prefix = seg0.prefix
        # use_decoder = seg0.use_decoder
        seed = seg0.infer_seed
        chunk_size = context.infer_config.stream_chunk_size

        if prompt2.strip():
            prompt_prefix = "[Ptts][Ptts][Ptts] "
            prompt_suffix = " [Stts][Ptts][Stts][Ptts][Stts]"
            prompt2 = f"{prompt_prefix}{prompt2}{prompt_suffix}"

        # NOTE: 加这个的原因:
        # https://github.com/lenML/ChatTTS-Forge/issues/133
        if txt_smp and not txt_smp.endswith("。"):
            txt_smp = txt_smp + "。"

        sr = 24000

        if not stream:
            with SeedContext(seed, cudnn_deterministic=False):
                results = infer.generate_audio(
                    text=texts,
                    spk_emb=spk_emb if spk_smp is None else None,
                    spk_smp=spk_smp,
                    txt_smp=txt_smp,
                    top_P=top_P,
                    top_K=top_K,
                    temperature=temperature,
                    prompt1=prompt1,
                    prompt2=prompt2,
                    prefix=prefix,
                )
                audio_arr: list[NP_AUDIO] = [
                    # NOTE: data[0] 的意思是 立体声 => mono audio
                    (sr, np.empty(0)) if data is None else (sr, data[0])
                    for data in results
                ]

                self.set_cache(segments=segments, context=context, value=audio_arr)
                return audio_arr
        else:

            def _gen() -> Generator[list[NP_AUDIO], None, None]:
                audio_arr_buff = None
                with SeedContext(seed, cudnn_deterministic=False):
                    for results in infer.generate_audio_stream(
                        text=texts,
                        spk_emb=spk_emb if spk_smp is None else None,
                        spk_smp=spk_smp,
                        txt_smp=txt_smp,
                        top_P=top_P,
                        top_K=top_K,
                        temperature=temperature,
                        prompt1=prompt1,
                        prompt2=prompt2,
                        prefix=prefix,
                        stream_chunk_size=chunk_size,
                    ):
                        results = [
                            (
                                np.empty(0)
                                # None 应该是生成失败, size === 0 是生成结束
                                if data is None or data.size == 0
                                # NOTE: data[0] 的意思是 立体声 => mono audio
                                else data[0]
                            )
                            for data in results
                        ]
                        audio_arr: list[NP_AUDIO] = [(sr, data) for data in results]
                        yield audio_arr

                        if audio_arr_buff is None:
                            audio_arr_buff = audio_arr
                        else:
                            for i, data in enumerate(results):
                                sr1, before = audio_arr_buff[i]
                                buff = np.concatenate([before, data], axis=0)
                                audio_arr_buff[i] = (sr1, buff)
                self.set_cache(segments=segments, context=context, value=audio_arr_buff)

            return _gen()
