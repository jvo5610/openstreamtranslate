"""Generate the OpenStreamTranslate architecture diagram."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.onprem.client import Client, Users
from diagrams.onprem.compute import Server
from diagrams.onprem.inmemory import Redis
from diagrams.onprem.monitoring import Prometheus
from diagrams.programming.framework import Fastapi


OUTPUT = Path(__file__).with_name("architecture")

GRAPH_ATTRIBUTES = {
    "bgcolor": "white",
    "fontname": "Arial",
    "fontsize": "18",
    "pad": "0.35",
    "ranksep": "0.8",
    "nodesep": "0.55",
    "splines": "spline",
}

NODE_ATTRIBUTES = {
    "fontname": "Arial",
    "fontsize": "11",
    "fontcolor": "#24153A",
}

EDGE_ATTRIBUTES = {
    "fontname": "Arial",
    "fontsize": "9",
    "color": "#6D35C5",
    "fontcolor": "#4B277B",
}


with Diagram(
    "OpenStreamTranslate",
    filename=str(OUTPUT),
    outformat="png",
    show=False,
    direction="LR",
    graph_attr=GRAPH_ATTRIBUTES,
    node_attr=NODE_ATTRIBUTES,
    edge_attr=EDGE_ATTRIBUTES,
):
    audience = Users("Audience\nweb player + overlay")
    production = Client("Studio / OBS\nmic · SRT · RTMP")

    with Cluster("Ingest + orchestration · CPU"):
        ingress = Fastapi("FastAPI\nWebSocket · API")

    with Cluster("GPU inference · workers x N"):
        asr = Server("ASR\nfaster-whisper\nlarge-v3-turbo")
        translation = Server("Translation\nTranslateGemma 4B\nllama.cpp")

    with Cluster("Delivery · CPU · replicas x N"):
        broker = Redis("Redis\nStreams · Pub/Sub")
        gateway = Fastapi("FastAPI gateway\nSSE · replay · export")

    metrics = Prometheus("Prometheus /metrics\nstructured logs")

    production >> Edge(label="PCM 16 kHz") >> ingress
    ingress >> Edge(label="audio + hotwords") >> asr
    asr >> Edge(label="text + glossary") >> translation
    translation >> Edge(label="bilingual captions") >> broker
    broker >> Edge(label="one event per session") >> gateway
    gateway >> Edge(label="SSE + replay") >> audience
    gateway >> Edge(label="metrics + logs", style="dashed") >> metrics
