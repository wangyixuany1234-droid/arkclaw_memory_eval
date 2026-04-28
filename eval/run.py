from __future__ import annotations

import argparse
import os
import shutil
import socket
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Set

from .config import load_config
from .pipeline import run_pipeline


def _parse_multi(value: str) -> Set[str]:
    return {v.strip() for v in value.split(",") if v.strip()}


def _get_free_port() -> int:
    """获取一个可用的端口号"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_http_server(directory: str, host: str, port: int) -> HTTPServer:
    """在指定目录启动 HTTP 服务器"""
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)
        
        def log_message(self, format, *args):
            """重写日志方法，减少输出"""
            pass
    
    server = HTTPServer((host, port), Handler)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Arkclaw 记忆功能自动化评估 - ingest → qa → judge → report",
    )
    parser.add_argument(
        "--cases",
        required=True,
        help="用例集 CSV 文件路径",
    )
    parser.add_argument(
        "--filter-priority",
        help="按优先级过滤，如 P0,P1",
    )
    parser.add_argument(
        "--filter-type",
        help="按记忆类型过滤，如 对话记忆,任务执行记忆",
    )
    parser.add_argument(
        "--filter-time",
        help="按时间维度过滤，如 短期（24 小时内）,中期（1-7 天）",
    )
    parser.add_argument(
        "--steps",
        default="ingest,qa,judge",
        help="执行步骤，逗号分隔：ingest,qa,judge，可选其一或组合",
    )
    parser.add_argument(
        "--new-session",
        choices=["ingest", "qa", "none"],
        default="none",
        help="在 ingest/qa 前是否启用新 session",
    )
    parser.add_argument(
        "--iteration-tag",
        required=True,
        help="本次评估迭代标识，如 2026-04-18-v1",
    )
    parser.add_argument(
        "--output-dir",
        default="result",
        help="结果输出目录，默认 result（建议与报表 ./report 分开）",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="配置文件路径（YAML），可选",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="评估完成后启动 HTTP 服务器并打开浏览器查看报表",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP 服务器绑定地址，默认 0.0.0.0（支持外部访问），使用 127.0.0.1 仅本地访问",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP 服务器端口，默认自动选择可用端口",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="启用模拟模式，无需真实网关也能生成演示数据（用于测试报表）",
    )

    args = parser.parse_args()

    steps = _parse_multi(args.steps)
    valid_steps = {"ingest", "qa", "judge"}
    if not steps.issubset(valid_steps):
        raise SystemExit(f"--steps 仅支持 {','.join(sorted(valid_steps))}，当前：{steps}")

    filter_priority = _parse_multi(args.filter_priority) if args.filter_priority else None
    filter_type = _parse_multi(args.filter_type) if args.filter_type else None
    filter_time = _parse_multi(args.filter_time) if args.filter_time else None

    cfg = load_config(args.config)

    results_path, summary_path = run_pipeline(
        csv_path=args.cases,
        cfg=cfg,
        filter_priorities=filter_priority,
        filter_types=filter_type,
        filter_times=filter_time,
        steps=steps,
        new_session_mode=args.new_session,
        iteration_tag=args.iteration_tag,
        output_dir=args.output_dir,
        mock_mode=args.mock,
    )

    print("评估完成：")
    print(f"  results.jsonl: {results_path}")
    print(f"  summary.csv  : {summary_path}")

    # 评估完成后，将关键结果同步到静态报表目录（若存在）
    report_dir = "report"
    if os.path.isdir(report_dir):
        try:
            dst_results = os.path.join(report_dir, "results.jsonl")
            dst_summary = os.path.join(report_dir, "summary.csv")
            shutil.copy2(results_path, dst_results)
            shutil.copy2(summary_path, dst_summary)
            print("报表数据已同步：")
            print(f"  {results_path} -> {dst_results}")
            print(f"  {summary_path} -> {dst_summary}")
        except Exception as exc:  # pragma: no cover - 文件系统环境相关
            print(f"[WARN] 拷贝结果到报表目录失败：{exc}")
    else:
        print(f"[INFO] 报表目录不存在，跳过结果同步：{report_dir}")

    # 启动 HTTP 服务器并打开浏览器（如果指定了 --serve）
    if args.serve:
        if os.path.isdir(report_dir):
            port = args.port if args.port else _get_free_port()
            host = args.host
            server = _start_http_server(report_dir, host, port)
            
            # 显示合适的访问地址
            if host == "0.0.0.0":
                # 如果绑定在 0.0.0.0，提供多个访问地址
                local_url = f"http://127.0.0.1:{port}/index.html"
                print("\n" + "=" * 60)
                print(f"🚀 报表服务器已启动：")
                print(f"   本地访问：{local_url}")
                print(f"   网络访问：http://<你的服务器IP>:{port}/index.html")
                print(f"   按 Ctrl+C 停止服务器")
                print("=" * 60 + "\n")
            else:
                url = f"http://{host}:{port}/index.html"
                print("\n" + "=" * 60)
                print(f"🚀 报表服务器已启动：")
                print(f"   访问地址：{url}")
                print(f"   按 Ctrl+C 停止服务器")
                print("=" * 60 + "\n")
            
            # 在新线程中打开浏览器（仅本地访问时）
            if host == "127.0.0.1" or host == "localhost":
                def open_browser():
                    webbrowser.open(f"http://127.0.0.1:{port}/index.html")
                threading.Thread(target=open_browser, daemon=True).start()
            
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\n服务器已停止。")
                server.shutdown()
        else:
            print(f"[ERROR] 报表目录不存在，无法启动服务器：{report_dir}")


if __name__ == "__main__":  # pragma: no cover
    main()
