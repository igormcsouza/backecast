import json
import runpy
from pathlib import Path

import aws_cdk as cdk

INFRA = Path(__file__).parent.parent


def test_app_tags_resources_with_project(monkeypatch, tmp_path):
    # app.py reads stage config from cdk.json context, normally injected by the CLI.
    ctx = json.loads((INFRA / "cdk.json").read_text())["context"]
    real_app = cdk.App
    monkeypatch.setattr(cdk, "App", lambda: real_app(context=ctx, outdir=str(tmp_path)))
    runpy.run_path(str(INFRA / "app.py"))

    template = json.loads((tmp_path / "Backecast-prod-Data.template.json").read_text())
    table = next(
        r for r in template["Resources"].values() if r["Type"] == "AWS::DynamoDB::Table"
    )
    assert {"Key": "project", "Value": "backecast"} in table["Properties"]["Tags"]
