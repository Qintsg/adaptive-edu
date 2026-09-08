#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT checkpoint 的 CPU/GPU 运行时门禁。
@Project : adaptive-edu
@File : mefkt_runtime.py
@Author : Qintsg
@Date : 2026-08-25
'''

from __future__ import annotations

import time

import torch
from mefkt_data_core import PreparedDataset
from mefkt_lite_data import SequenceStore, collate_sequence_indices
from mefkt_models import BaseMEFKT


def runtime_validate(
    model: BaseMEFKT,
    prepared: PreparedDataset,
    threads: int,
    max_parameters: int,
    max_gpu_memory_gb: float,
    sequence_length: int,
) -> dict[str, object]:
    """
    验证 CPU 加载推理，并在有 CUDA 时检查 GPU 峰值显存。

    :param model: 已训练模型。
    :param prepared: 预处理数据集。
    :param threads: CPU 推理线程数。
    :param max_parameters: 参数量上限。
    :param max_gpu_memory_gb: GPU 峰值显存上限。
    :param sequence_length: 验证序列长度。
    :returns: 运行时门禁结果。
    """
    parameters = sum(parameter.numel() for parameter in model.parameters())
    original_threads = torch.get_num_threads()
    torch.set_num_threads(max(1, threads))
    try:
        model = model.to("cpu").eval()
        store = SequenceStore(prepared.root, "test")
        if len(store) == 0:
            return {"passed": False, "reason": "test split empty", "parameters": parameters}
        batch = collate_sequence_indices([0], store, max(sequence_length, 64))
        start = time.perf_counter()
        with torch.no_grad():
            logits, mask, state = model(*batch[:4])
        elapsed = time.perf_counter() - start
        effective_mask = mask & batch[4]
        finite = bool(torch.isfinite(logits).all()) and bool(torch.isfinite(state.context).all())
        cpu_passed = finite and bool(effective_mask.any()) and parameters <= max_parameters
        gpu_result: dict[str, object] = {"gpu_available": False, "gpu_passed": None}
        if torch.cuda.is_available():
            gpu_device = torch.device("cuda")
            gpu_model = model.to(gpu_device).eval()
            gpu_batch = tuple(value.to(gpu_device, non_blocking=True) for value in batch[:4])
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(gpu_device)
            with torch.no_grad():
                gpu_model(*gpu_batch)
            peak_allocated_gb = torch.cuda.max_memory_allocated(gpu_device) / (1024**3)
            peak_reserved_gb = torch.cuda.max_memory_reserved(gpu_device) / (1024**3)
            peak_memory_gb = max(peak_allocated_gb, peak_reserved_gb)
            gpu_passed = peak_memory_gb <= max_gpu_memory_gb
            gpu_result = {
                "gpu_available": True,
                "gpu_passed": gpu_passed,
                "gpu_peak_memory_gb": peak_memory_gb,
                "gpu_peak_allocated_gb": peak_allocated_gb,
                "gpu_peak_reserved_gb": peak_reserved_gb,
                "gpu_device": torch.cuda.get_device_name(gpu_device),
            }
            model = gpu_model.to("cpu").eval()
        else:
            gpu_passed = None
        passed = cpu_passed and gpu_passed is not False
        return {
            "passed": passed,
            "cpu_passed": cpu_passed,
            "parameters": parameters,
            "max_parameters": max_parameters,
            "threads": threads,
            "cpu_seconds": elapsed,
            "finite": finite,
            "output_shape": list(logits.shape),
            "memory_shape": list(state.memory.shape) if state.memory is not None else [0],
            "max_gpu_memory_gb": max_gpu_memory_gb,
            **gpu_result,
        }
    finally:
        torch.set_num_threads(original_threads)
