"""Cloud ASR protocol tests using local HTTP fixtures; no model downloads."""
from __future__ import annotations

import json
import subprocess
from urllib.parse import urlsplit

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from clipflow.asr import Recognition, TimedText, recognize
from clipflow import cloud_client, cloud_server


def test_endpoint_tls_and_no_tokens_in_url():
    assert cloud_client._endpoint("https://example.org") == "https://example.org/v1/transcribe"
    assert cloud_client._endpoint("http://localhost:8000") == "http://localhost:8000/v1/transcribe"
    for url in ["http://example.org", "https://admin:secret@example.org", "https://example.org/?token=test", "https://example.org/path"]:
        with pytest.raises(ValueError):
            cloud_client._endpoint(url)


def test_server_bearer_fail_closed(monkeypatch):
    monkeypatch.delenv("CLIPFLOW_ASR_SERVER_KEY",raising=False)
    with TestClient(cloud_server.app) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/v1/transcribe",content=b"audio",headers={"content-type":"audio/flac"}).status_code == 503
    monkeypatch.setenv("CLIPFLOW_ASR_SERVER_KEY","test-secret-not-to-log")
    with TestClient(cloud_server.app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/v1/transcribe",content=b"audio",headers={"content-type":"audio/flac"}).status_code == 401
        assert client.post("/v1/transcribe",content=b"audio",headers={"content-type":"audio/flac","authorization":"Bearer invalid"}).status_code == 401
        assert client.post("/v1/transcribe",content=b"audio",headers={"content-type":"audio/mpeg","authorization":"Bearer test-secret-not-to-log"}).status_code == 415


def test_dispatch_selects_cloud_without_local_whisper(monkeypatch, tmp_path):
    audio=tmp_path/"unused.flac";audio.write_bytes(b"not actual audio")
    monkeypatch.setenv("CLIPFLOW_ASR_URL","https://asr.example")
    monkeypatch.setenv("CLIPFLOW_ASR_API_KEY","fixture")
    real_cloud=cloud_client.recognize_cloud
    monkeypatch.setattr(cloud_client,"recognize_cloud",lambda *args, **kwargs: Recognition([TimedText(0,1,"云端")],[TimedText(0,1,"云端")],"cloud_word_timestamps","zh"))
    result=recognize(audio, backend="auto")
    assert result.captions[0].text=="云端"
    monkeypatch.delenv("CLIPFLOW_ASR_API_KEY")
    with pytest.raises(RuntimeError,match="配置不完整"):
        recognize(audio,backend="auto")
    monkeypatch.setattr(cloud_client,"recognize_cloud",real_cloud)
    with pytest.raises(RuntimeError,match="尚未配置"):
        recognize(audio,backend="cloud")


def test_audio_only_end_to_end_mocked_inference(tmp_path, monkeypatch):
    audio=tmp_path/"speech.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","color=c=black:r=12:s=160x288:d=2.2",
                    "-f","lavfi","-i","sine=frequency=440:duration=2.2",
                    "-shortest","-c:v","libx264","-c:a","aac",str(audio)],check=True)
    monkeypatch.setenv("CLIPFLOW_ASR_SERVER_KEY","secret")
    monkeypatch.setenv("CLIPFLOW_ASR_URL","http://127.0.0.1:8000")
    monkeypatch.setenv("CLIPFLOW_ASR_API_KEY","secret")
    monkeypatch.setattr(cloud_server,"_model",lambda:object())
    monkeypatch.setattr(cloud_server,"recognize_local",lambda *args,**kwargs: Recognition(
        [TimedText(.20,.85,"大家好，我是律师。")],[TimedText(.20,.4,"大家好，"),TimedText(.4,.85,"我是律师。")],"word_timestamps","zh"))

    class _Response:
        def __init__(self, content): self.content=content
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,max_size): return self.content[:max_size]
    class _LocalOpener:
        def open(self,request,timeout=None):
            assert request.get_method()=="POST"
            assert request.data.startswith(b"fLaC")
            assert "mp4" not in request.headers.get("Content-type","")
            with TestClient(cloud_server.app) as client:
                uri=urlsplit(request.full_url)
                response=client.post(uri.path+"?"+uri.query,content=request.data,headers=dict(request.headers))
            assert response.status_code==200, response.text
            return _Response(response.content)
    monkeypatch.setattr(cloud_client,"build_opener",lambda *a:_LocalOpener())
    recognition=cloud_client.recognize_cloud(audio)
    assert recognition.alignment=="cloud_word_timestamps"
    assert "".join(w.text for w in recognition.words)=="大家好，我是律师。"
    assert recognition.captions[0].start==pytest.approx(.20)
    assert recognition.captions[0].end==pytest.approx(.85)
