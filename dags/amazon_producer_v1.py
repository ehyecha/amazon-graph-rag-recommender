import json
import time
from kafka import KafkaProducer  # 또는 confluent_kafka
import gzip
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import os

# 위에서 만든 파서 함수를 그대로 가져옵니다.
# (파일 상단에 amazon_metadata_parser 함수가 있다고 가정)

# 1. 경로 확인
FILE_PATH = '/opt/airflow/data/electronics_ontology_sample.json'

def produce_to_kafka():
    producer = KafkaProducer(
        bootstrap_servers=['kafka:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    with open(FILE_PATH, 'r') as f:
        for line in f:
            data = json.loads(line)
            producer.send('amazon_electronics', value=data)
    producer.flush()

with DAG('amazon_producer_dag', start_date=datetime(2023, 1, 1), schedule_interval='@once') as dag:
    produce_task = PythonOperator(
        task_id='send_to_kafka',
        python_callable=produce_to_kafka
    )