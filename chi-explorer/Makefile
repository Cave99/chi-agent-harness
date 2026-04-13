.PHONY: backend frontend dev

# Run the FastAPI backend
backend:
	@echo "Starting FastAPI backend on port 5001..."
	python3 -m uvicorn app:app --host 0.0.0.0 --port 5001 --reload

# Run the React frontend (from sister directory)
frontend:
	@echo "Starting React frontend..."
	cd ../frontend && npm run dev -- --port 5173

# Optional: Run both (if user has 'make -j')
dev:
	@make -j2 backend frontend
