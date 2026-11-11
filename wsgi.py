from app import create_app
import metrics

app = create_app()
metrics.start(app.config['USAGE_DATABASE'])
