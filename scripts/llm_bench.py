"""Decode speed + tool-call correctness per model, and FRS fps while generating."""
import json, sys, time, threading, httpx
TOOLS = [{"type": "function", "function": {"name": "search_events", "description": "Search events",
          "parameters": {"type": "object", "properties": {"type": {"type": "string"}, "since_minutes": {"type": "number"}}}}}]
def frs_fps():
    return httpx.get("https://127.0.0.1:8000/api/metrics", verify=False).json()["analysis"]["station_analysed_fps"]
for model in sys.argv[1:]:
    t = time.time()
    r = httpx.post("http://127.0.0.1:11434/api/chat", timeout=600, json={"model": model, "stream": False, "think": False,
        "messages": [{"role": "user", "content": "Were there any fights in the last hour?"}], "tools": TOOLS}).json()
    tc = r["message"].get("tool_calls")
    samples = []
    stop = threading.Event()
    def sampler():
        while not stop.is_set():
            time.sleep(8); samples.append(frs_fps())
    th = threading.Thread(target=sampler); th.start()
    g = httpx.post("http://127.0.0.1:11434/api/generate", timeout=600, json={"model": model, "stream": False, "think": False,
        "prompt": "Write a detailed 600-word incident report about a scuffle at a gate.", "options": {"num_predict": 700}}).json()
    stop.set(); th.join()
    tps = g["eval_count"] / (g["eval_duration"] / 1e9)
    print(json.dumps({"model": model, "first_call_s": round(time.time() - t, 1), "tool_call": tc[0]["function"] if tc else None,
                      "decode_tok_s": round(tps, 1), "gen_s": round(g["eval_duration"] / 1e9, 1),
                      "frs_station_fps_during": round(sum(samples[1:]) / max(len(samples) - 1, 1), 1) if samples else None}))
