FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY core.py forecast.py learning_store.py learning_ui.py repo_selection.py repo_selection_ui.py mobile_notify.py mobile_notify_ui.py monitor.py ./
COPY run.sh /app/run.sh
RUN chmod 0755 /app/run.sh
CMD ["/app/run.sh"]
