import json
import os
import re
import sys
import time

import requests

# 强制设置标准输出为UTF-8编码（解决Windows cmd下emoji无法打印的问题）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# =====================================================================
# 模块 1：网络环境强力净化 (防止 10054 / 10053 报错)
# =====================================================================
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["all_proxy"] = ""
os.environ["ALL_PROXY"] = ""

# =====================================================================
# 模块 2：用户全局配置区
# =====================================================================
# 优先读环境变量 MINERU_TOKEN，未设置时使用下方占位字符串（请替换或设置环境变量）
TOKEN = os.environ.get("MINERU_TOKEN", "").strip() or "你在MinerU上申请到的TOKEN" #在or的后面替换成你的MinerU的TOKEN

# 🚀 极简双模输入引擎：优先读取命令行参数，否则回退到手动输入
if len(sys.argv) > 1:
    raw_path = sys.argv[1]
    print(f"📥 [自动模式] 已接收到传入路径: {raw_path}")
else:
    print(
        "💡 提示：你可以输入...\n"
        "  1. 单个 PDF 路径\n"
        "  2. 包含多个 PDF 的文件夹路径\n"
        "  3. 包含多个 PDF 路径的 TXT 文本文件路径"
    )
    raw_path = input("👉 请在此处粘贴路径 (然后按回车): ")

INPUT_PATH = raw_path.strip('"').strip("'")

# 解析结果的保存目标位置
SAVE_DIR = r"H:\ObsidianVaults\Literature\文献笔记"  # 替换成你的 Obsidian 中的文献笔记保存路径

BASE_URL = "https://mineru.net/api/v1/agent"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
}

# 请求超时：(连接秒, 读取秒)
TIMEOUT_API = (15, 120)
TIMEOUT_UPLOAD = (15, 1200)
TIMEOUT_DOWNLOAD = (15, 600)
PROXIES = {"http": None, "https": None}

_PLACEHOLDER_TOKEN = "你在MinerU上申请到的TOKEN"


def _response_json(resp):
    try:
        return resp.json(), None
    except json.JSONDecodeError:
        text = resp.text or ""
        snippet = text[:400].replace("\n", " ")
        return None, f"响应非 JSON: {snippet}"


def _yaml_escape_double_quoted(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _read_txt_lines(path):
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


# =====================================================================
# 模块 3：核心功能 - 提交 PDF 并等待解析
# =====================================================================
def parse_by_file(file_path, language="en"):
    file_name = os.path.basename(file_path)

    print(f"🚀 [步骤 1] 正在申请安全上传通道: {file_name}")
    data = {"file_name": file_name, "language": language}

    try:
        resp = requests.post(
            f"{BASE_URL}/parse/file",
            json=data,
            headers=HEADERS,
            proxies=PROXIES,
            timeout=TIMEOUT_API,
        )
    except requests.RequestException as e:
        print(f"❌ 申请通道网络异常: {e}")
        return None

    if resp.status_code != 200:
        print(
            f"❌ 申请通道失败, HTTP状态码: {resp.status_code}, 正文片段: {(resp.text or '')[:200]}"
        )
        return None

    result, err = _response_json(resp)
    if err:
        print(f"❌ {err}")
        return None
    if result.get("code") != 0:
        print(f"❌ 获取上传链接失败: {result.get('msg')}")
        return None

    data_obj = result.get("data")
    if not isinstance(data_obj, dict):
        print("❌ 接口返回缺少 data 或格式异常")
        return None
    task_id = data_obj.get("task_id")
    file_url = data_obj.get("file_url")
    if not task_id or not file_url:
        print("❌ 接口返回缺少 task_id 或 file_url")
        return None
    print(f"✅ 通道开启成功！任务 ID: {task_id}")

    print("📤 [步骤 2] 正在将文献直传至云端...")
    try:
        with open(file_path, "rb") as f:
            put_resp = requests.put(
                file_url, data=f, proxies=PROXIES, timeout=TIMEOUT_UPLOAD
            )
    except requests.RequestException as e:
        print(f"❌ 上传网络异常: {e}")
        return None
    except OSError as e:
        print(f"❌ 读取本地文件失败: {e}")
        return None

    if put_resp.status_code not in (200, 201):
        print(f"❌ 文件上传云端失败, HTTP {put_resp.status_code}")
        return None

    print("✅ 文件成功送达云端！")
    print("⏳ [步骤 3] 视觉大模型(VLM)正在拼命解析文字与图表...")
    return poll_result(task_id)


# =====================================================================
# 模块 4：核心功能 - 轮询等待与数据清洗
# =====================================================================
def poll_result(task_id, timeout=600, interval=10):
    state_labels = {
        "pending": "排队中",
        "running": "深度解析中",
        "waiting-file": "等待文件上传",
    }
    start = time.time()

    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"{BASE_URL}/parse/{task_id}",
                headers=HEADERS,
                proxies=PROXIES,
                timeout=TIMEOUT_API,
            )
        except requests.RequestException as e:
            print(f"❌ 查询状态网络异常: {e}")
            return None

        if resp.status_code != 200:
            print(f"❌ 查询状态 HTTP 异常: {resp.status_code}")
            return None

        result, err = _response_json(resp)
        if err:
            print(f"❌ {err}")
            return None

        if result.get("code") != 0:
            print(f"❌ 查询状态报错: {result.get('msg')}")
            return None

        data = result.get("data")
        if not isinstance(data, dict):
            print("❌ 状态接口返回 data 格式异常")
            return None

        state = data.get("state")
        elapsed = int(time.time() - start)

        if state == "done":
            markdown_url = data.get("markdown_url")
            if not markdown_url:
                print("❌ 解析完成但未返回 markdown_url")
                return None
            print(f"🎉 [{elapsed}s] 解析彻底完成！")
            print("⬇️ [步骤 4] 正在下载排版好的 Markdown 文本...")

            try:
                md_resp = requests.get(
                    markdown_url, proxies=PROXIES, timeout=TIMEOUT_DOWNLOAD
                )
            except requests.RequestException as e:
                print(f"❌ 下载 Markdown 网络异常: {e}")
                return None

            if md_resp.status_code != 200:
                print(f"❌ 下载 Markdown 失败, HTTP {md_resp.status_code}")
                return None

            md_resp.encoding = "utf-8"
            md_text = md_resp.text

            print("🧽 [步骤 4.5] 正在清洗公式中的加减乘除乱码...")
            md_text = (
                md_text.replace("\x01", "+")
                .replace("\x02", "-")
                .replace("\x03", "×")
                .replace("\x04", "÷")
                .replace("Ã½", "ý")
            )

            return md_text

        if state == "failed":
            print(
                f"❌ [{elapsed}s] 解析失败: {data.get('err_msg', '未知错误')}"
            )
            return None

        print(f"[{elapsed}s] 状态: {state_labels.get(state, state)}...")
        time.sleep(interval)

    print(f"⚠️ 解析超时 ({timeout}s)，文献太长，请稍后排查。")
    return None


# =====================================================================
# 模块 5：系统入口与 Obsidian 整合
# =====================================================================
def save_to_obsidian(pdf_file_path):
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    markdown_content = parse_by_file(pdf_file_path, language="en")

    if not markdown_content:
        print(
            f"❌ 跳过（解析失败或无内容）: {os.path.basename(pdf_file_path)}"
        )
        return

    file_name = os.path.basename(pdf_file_path)
    base_name = os.path.splitext(file_name)[0]

    year_match = re.search(r"(19|20)\d{2}", base_name)
    year = year_match.group(0) if year_match else "未知年份"

    output_path = os.path.join(SAVE_DIR, f"{base_name}_pure.md")
    title_yaml = _yaml_escape_double_quoted(base_name)

    yaml_frontmatter = f"""---
title: "{title_yaml}"
year: "{year}"
tags:
  - #文献笔记
  - #矿床学
  - #成因机制
status: 🟢已解析
---

"""

    with open(output_path, "w", encoding="utf-8") as md_file:
        md_file.write(yaml_frontmatter + markdown_content)

    print("-" * 40)
    print(f"🎯 成功！已生成笔记: {output_path}")


# =====================================================================
# 🚀 模块 6：批量任务调度器
# =====================================================================
if __name__ == "__main__":
    if TOKEN == _PLACEHOLDER_TOKEN:
        print(
            "⚠️ 未检测到有效 Token：请设置环境变量 MINERU_TOKEN，"
            "或在本文件中将占位字符串改为你在 MinerU 申请的 TOKEN。"
        )

    pdf_tasks = []

    if os.path.isdir(INPUT_PATH):
        print("\n📂 检测到文件夹输入，正在扫描其中的 PDF 文献...")
        for file in os.listdir(INPUT_PATH):
            if file.lower().endswith(".pdf"):
                pdf_tasks.append(os.path.join(INPUT_PATH, file))

    elif os.path.isfile(INPUT_PATH) and INPUT_PATH.lower().endswith(".txt"):
        print("\n📝 检测到 TXT 路径列表，正在提取文献路径...")
        try:
            lines = _read_txt_lines(INPUT_PATH)
        except OSError as e:
            print(f"❌ 无法读取 TXT 文件: {e}")
            sys.exit(1)
        for line in lines:
            clean_path = line.strip().strip('"').strip("'")
            if clean_path and os.path.isfile(clean_path) and clean_path.lower().endswith(".pdf"):
                pdf_tasks.append(clean_path)
            elif clean_path:
                print(f"⚠️ 警告：忽略无效或不存在的路径 -> {clean_path}")

    elif os.path.isfile(INPUT_PATH) and INPUT_PATH.lower().endswith(".pdf"):
        print("\n📄 检测到单文件输入。")
        pdf_tasks.append(INPUT_PATH)

    else:
        print("\n❌ 错误：输入无效。")
        sys.exit(1)

    pdf_tasks.sort()

    total_files = len(pdf_tasks)
    if total_files == 0:
        print("📭 没有找到任何有效的 PDF 任务，程序退出。")
        sys.exit(1)

    print(f"🔥 共提取到 {total_files} 篇待解析文献。准备开工！\n" + "=" * 50)

    for index, pdf_path in enumerate(pdf_tasks, start=1):
        print(
            f"\n▶️ [进度 {index}/{total_files}] 正在处理文献: {os.path.basename(pdf_path)}"
        )
        save_to_obsidian(pdf_path)

        if index < total_files:
            print("☕ 休息 3 秒钟后继续下一篇，防止触发服务器流控...")
            time.sleep(3)

    print("\n" + "=" * 50)
    print("🏆 批量任务全部完成！去 Obsidian 里检阅你的文献大军吧！")
