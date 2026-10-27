"""Count visible original-frame text for choosing a minimally cluttered still.

Chinese + English Tesseract data are required. No network OCR or private-media
upload is performed. We measure only original pixels BEFORE the ClipFlow 001
watermark is drawn. OCR can miss stylized/low-contrast text, so measurements
are technical estimates, not claims of perfect character recognition.
"""
from __future__ import annotations

from functools import lru_cache
import shutil


@lru_cache(maxsize=1)
def ocr_language() -> str:
    if not shutil.which('tesseract'):
        raise RuntimeError('无法选择文字最少的一帧：缺少 Tesseract OCR 可执行程序')
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError('无法选择文字最少的一帧：需安装 pytesseract') from exc
    try:
        langs = set(pytesseract.get_languages(config=''))
    except Exception as exc:
        raise RuntimeError('Tesseract OCR 无法初始化；不允许假设文字检测完成') from exc
    chinese = 'chi_sim' if 'chi_sim' in langs else ('HanS' if 'HanS' in langs else None)
    if not chinese:
        raise RuntimeError('文字最少截图需要 Tesseract 简体中文语言包 chi_sim 或 HanS')
    return chinese + ('+eng' if 'eng' in langs else '')


def count_visible_text(frame, *, language: str | None = None) -> tuple[int,float]:
    """Return (recognized character count, recognized bbox area fraction).

    Only words with confidence >=35 are counted to reduce textured background
    false positives. Character count is the primary ranking; bbox is tie-break.
    """
    import cv2
    import numpy as np
    import pytesseract
    from pytesseract import Output

    lang = language or ocr_language()
    h,w = frame.shape[:2]
    if h<8 or w<8:
        raise ValueError('无法从过小视频帧识别文字')
    # Moderate downscale helps OCR throughput on many segment stills.
    scale = min(1., 1100./max(h,w))
    image = (cv2.resize(frame,(max(8,round(w*scale)),max(8,round(h*scale))),
                        interpolation=cv2.INTER_AREA) if scale<1 else frame)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    try:
        data = pytesseract.image_to_data(rgb, lang=lang, config='--psm 11',
                                         output_type=Output.DICT)
    except Exception as exc:
        raise RuntimeError('截图 OCR 文字计数失败，不能声称已选到文字最少帧') from exc
    length = 0
    area = 0
    for i, token in enumerate(data.get('text',[])):
        word = str(token).strip()
        if not word:
            continue
        try: confidence = float(data['conf'][i])
        except (ValueError,IndexError,TypeError,KeyError): continue
        if not np.isfinite(confidence) or confidence < 35:
            continue
        chars = [c for c in word if c.isalnum()]
        if not chars:
            continue
        length += len(chars)
        area += max(0,int(data['width'][i]))*max(0,int(data['height'][i]))
    return length, round(area / max(1,image.shape[0]*image.shape[1]),6)
