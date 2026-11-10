from app import create_app, start_collector

app = create_app()
start_collector(app)
