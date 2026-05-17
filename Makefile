CURRENT_DIR = $(shell pwd)
include .env
export

prepare-dirs:
	mkdir -p data/chroma_data
	mkdir -p data/history

run-chroma:
	docker run -d \
  	--name chromadb \
  	-p 8000:8000 \
  	-v ./data/chroma_data:/chroma/chroma \
  	chromadb/chroma:latest

latex:
	/Library/TeX/texbin/pdflatex -interaction=nonstopmode ${CURRENT_DIR}/data/llm-workflow-workshop.tex || true
	@echo "============================================================"
	@echo "PDF created: interview_questions.pdf"
	@ls -lh interview_questions.pdf 2>/dev/null || echo "PDF not found in current directory"
	@echo "============================================================"
# 	rm ${CURRENT_DIR}/*.log ${CURRENT_DIR}/*.aux ${CURRENT_DIR}/*.out 2>/dev/null || true

list-models:
	curl -s https://api.studio.nebius.com/v1/models \
		-H "Authorization: Bearer ${NEBIUS_API_KEY}" \
		| python3 -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin).get('data',[])]"

chat:
	DATA_DIR=${CURRENT_DIR}/data/history PYTHONPATH=${CURRENT_DIR} uv run python scripts/chat.py

skill:
	uv run python scripts/prepare_skill.py

skill-install:
	uv run python scripts/prepare_skill.py --install

run-jupyter:
	DATA_DIR=${CURRENT_DIR}/data \
	PYTHONPATH=${CURRENT_DIR}/src \
	ENV_PATH=${CURRENT_DIR}/.env \
	jupyter notebook scripts --ip 0.0.0.0 --port 8899 --NotebookApp.token='' --NotebookApp.password='' --allow-root --no-browser 
