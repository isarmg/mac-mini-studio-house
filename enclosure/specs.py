"""Retained calibrated source observations, distinct from current design dimensions."""
import json
from . import ROOT

def source_report(model):
    if model not in ('mac-mini','mac-studio'):raise ValueError('Unknown model')
    return json.loads((ROOT/'data/reference'/(model+'-observations.json')).read_text(encoding='utf-8'))
