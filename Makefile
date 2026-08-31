# IRIS artifact evaluation convenience targets.
# All targets assume `conda activate iris-ae` first (or `bash setup.sh`).

PY = python
DATASET ?= $(if $(wildcard IRIS-dataset/index.json),IRIS-dataset,../IRIS-dataset)
SCRIPTS = scripts
RESULTS = results

.PHONY: help bench smoke sweep clean tests summary health

help:
	@echo "make smoke         Run bv_n120 × 3 variants with the paper's mapping (~3 min; needs make bench)"
	@echo "make sweep         Run 8-bench × 3-variant × 3-arch × n=120/180/240 (multi-hour)"
	@echo "make bench         Copy benchmarks + mapping caches from the IRIS-dataset (DATASET=$(DATASET))"
	@echo "make tests         Run EES post-condition unit tests + verify_extra_opt"
	@echo "make summary       Write results/summary.csv from current results"
	@echo "make clean         Remove results/ and figures/"

bench:
	$(PY) $(SCRIPTS)/seed_from_dataset.py --dataset $(DATASET)

smoke:
	$(PY) $(SCRIPTS)/seed_from_dataset.py --dataset $(DATASET) --results $(PWD)/$(RESULTS)/_smoke --benches bv_n120 --archs F120
	@for v in qucomm iris_opt0 iris_opt1; do \
	  RESULTS_DIR=$(PWD)/$(RESULTS)/_smoke bash $(SCRIPTS)/run_$$v.sh bv_n120 F120 ILP > /tmp/smoke_$$v.log 2>&1 || exit 1; \
	  echo "  $$v done"; \
	done
	@echo "Smoke done. See $(RESULTS)/_smoke/"

sweep:
	RESULTS_DIR=$(PWD)/$(RESULTS)/_full bash $(SCRIPTS)/reproduce_all.sh

tests:
	$(PY) tests/test_ees_postcondition.py
	$(PY) tests/verify_extra_opt.py --root $(RESULTS)/_smoke

summary:
	$(PY) $(SCRIPTS)/summarize_results.py --root $(RESULTS)/_full

clean:
	rm -rf $(RESULTS)/* figures/*.pdf figures/*.png

health:
	bash $(SCRIPTS)/health_check.sh
