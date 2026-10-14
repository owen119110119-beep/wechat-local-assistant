"""Local CPU transcription; never send private audio to a remote service."""
import argparse
import json
import pathlib
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="?")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        from huggingface_hub import snapshot_download
        snapshot_download("Systran/faster-whisper-base", local_dir=args.model_dir)
        print("local speech model downloaded")
        return
    from faster_whisper import WhisperModel
    assert args.audio and pathlib.Path(args.audio).is_file()
    model = WhisperModel(args.model_dir, device="cpu", compute_type="int8", local_files_only=True, cpu_threads=4)
    segments, info = model.transcribe(args.audio, language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是普通话，使用简体中文记录用户的需求。")
    text = "".join(segment.text for segment in segments).strip()
    print(json.dumps({"text": text, "language": info.language, "duration": info.duration}, ensure_ascii=True))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("LOCAL_TRANSCRIPTION_FAILED", file=sys.stderr)
        sys.exit(2)
