PY := .venv/bin/python
.PHONY: help run status logs restart test smoke frontend eval-violence eval-vlm frs-impact

help:            ## list commands
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/\t/'
run:             ## run in the foreground (use the systemd unit in production)
	$(PY) -m vigil.main
status:          ## service + readiness
	systemctl --user --no-pager status vigil | head -5; curl -sk https://127.0.0.1:8090/api/ready; echo
logs:            ## follow structured logs
	tail -f data/logs/vigil.log
restart:         ## restart the service
	systemctl --user restart vigil
test:            ## unit + integration tests (isolated temp data dir, no GPU needed)
	$(PY) -m pytest
smoke:           ## end-to-end API smoke test against the running service
	$(PY) scripts/smoke_api.py 20
frontend:        ## build the UI into frontend/dist (served by the backend)
	cd frontend && npm run build
eval-violence:   ## violence cascade on labelled clips through the production code path
	$(PY) scripts/eval_violence_cascade.py data/testclips2
eval-vlm:        ## VLM verification stage on fights vs hard negatives
	$(PY) scripts/eval_vlm_verifier.py data/testclips2 10
frs-impact:      ## sample the FRS backend's own analyzer metrics for 90 s
	$(PY) scripts/frs_impact.py 90
sim-webcam:      ## stream a video through the browser-webcam protocol (/ws/ingest) as a browser would
	$(PY) scripts/sim_webcam.py /home/vajra/umeshdr/frs_final/netra/data/test/walkthrough.mp4 40
demo-data:       ## regenerate synthetic demo data (flagged is_demo, watermarked)
	$(PY) -c "import sys;sys.path.insert(0,'scripts');from api import c;print(c.post('/api/demo/data?hours=24').json())"
demo-clear:      ## remove all synthetic demo data
	$(PY) -c "import sys;sys.path.insert(0,'scripts');from api import c;print(c.delete('/api/demo/data').json())"
