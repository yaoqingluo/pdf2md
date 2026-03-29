import os
import time
import re
import requests
import sys

# 强制设置标准输出为UTF-8编码（解决Windows cmd下emoji无法打印的问题）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# =====================================================================
# 模块 1：网络环境强力净化 (防止 10054 / 10053 报错)
# =====================================================================
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['all_proxy'] = ''
os.environ['ALL_PROXY'] = ''

# =====================================================================
# 模块 2：用户全局配置区
# =====================================================================
TOKEN = "填入你的api token"  # 记得填入你的 MinerU Token
SAVE_DIR = r"H:\ObsidianVaults\Literature\文献笔记" #换成你的保存路径

BASE_URL = "https://mineru.net/api/v1/agent"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}", 
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36" 
}

# =====================================================================
# 模块 3：核心功能 - 提交 PDF 并等待解析
# =====================================================================
def parse_by_file(file_path, language="en"):
    file_name = os.path.basename(file_path)

    print(f"🚀 [步骤 1] 正在申请安全上传通道: {file_name}")
    data = {"file_name": file_name, "language": language}
    
    resp = requests.post(f"{BASE_URL}/parse/file", json=data, headers=HEADERS, proxies={"http": None, "https": None})
    
    if resp.status_code != 200:
        print(f"❌ 申请通道失败, HTTP状态码: {resp.status_code}")
        return None
        
    result = resp.json()
    if result.get("code") != 0:
        print(f"❌ 获取上传链接失败: {result.get('msg')}")
        return None

    task_id = result["data"]["task_id"]
    file_url = result["data"]["file_url"] 
    print(f"✅ 通道开启成功！任务 ID: {task_id}")

    print(f"📤 [步骤 2] 正在将文献直传至云端...")
    with open(file_path, "rb") as f:
        put_resp = requests.put(file_url, data=f, proxies={"http": None, "https": None})
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
    state_labels = {"pending": "排队中", "running": "深度解析中", "waiting-file": "等待文件上传"}
    start = time.time() 
    
    while time.time() - start < timeout:
        resp = requests.get(f"{BASE_URL}/parse/{task_id}", headers=HEADERS, proxies={"http": None, "https": None})
        result = resp.json()
        
        if result.get("code") != 0:
            print(f"❌ 查询状态报错: {result.get('msg')}")
            return None
            
        state = result["data"]["state"]
        elapsed = int(time.time() - start)

        if state == "done":
            markdown_url = result["data"]["markdown_url"]
            print(f"🎉 [{elapsed}s] 解析彻底完成！")
            print(f"⬇️ [步骤 4] 正在下载排版好的 Markdown 文本...")
            
            md_resp = requests.get(markdown_url, proxies={"http": None, "https": None})
            md_resp.encoding = 'utf-8' 
            md_text = md_resp.text

            print("🧽 [步骤 4.5] 正在清洗公式中的加减乘除乱码...")
            md_text = md_text.replace('\x01', '+').replace('\x02', '-').replace('\x03', '×').replace('\x04', '÷').replace('Ã½', 'ý')

            return md_text 
        
        if state == "failed":
            print(f"❌ [{elapsed}s] 解析失败: {result['data'].get('err_msg', '未知错误')}")
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

    if markdown_content:
        file_name = os.path.basename(pdf_file_path)
        base_name = os.path.splitext(file_name)[0]
        
        year_match = re.search(r'(19|20)\d{2}', base_name)
        year = year_match.group(0) if year_match else "未知年份"

        output_path = os.path.join(SAVE_DIR, f"{base_name}_pure.md")

        yaml_frontmatter = f"""---
title: "{base_name}"
year: {year}
tags:
  - #文献笔记
  - #伟晶岩
  - #Li矿化
status: 🟢已解析
---

"""
        with open(output_path, "w", encoding="utf-8") as md_file:
            md_file.write(yaml_frontmatter + markdown_content)

        # 这是给 Claudian 插件抓取的双链回显
        print(f"[[文献笔记/{base_name}_pure.md]]")
        print("-" * 40)
        print(f"🎯 成功！已生成笔记: {output_path}")

# =====================================================================
# 🚀 模块 6：智能输入引擎与批量任务调度器
# =====================================================================
# =====================================================================
# 🚀 模块 6：智能输入引擎与批量任务调度器
# =====================================================================
if __name__ == "__main__":
    raw_inputs = []

    # 1. 接收输入（支持命令行或手动粘贴）
    if len(sys.argv) > 1:
        raw_inputs = sys.argv[1:]
        print(f"📥 [自动模式] 已接收到外部传入的参数...")
    else:
        print("💡 提示：你可以输入以下任意一种：")
        print("  1. 单个或多个 PDF 路径（直接粘贴即可，支持换行或空格分隔）")
        print("  2. 包含多个 PDF 的文件夹路径")
        print("  3. 包含多个 PDF 路径的 TXT 文本文件路径")
        print("  👉 输入完成后，按两下回车结束：")
        while True:
            try:
                line = input()
                if line.strip() == "":
                    break
                raw_inputs.append(line)
            except EOFError:
                break

    # 2. 暴力清洗与拆分（应对换行、空格、引号混杂的极端情况）
    pdf_tasks = []
    for item in raw_inputs:
        # 绝杀：如果外部传入的参数本身包含换行符，先按换行切开
        for line in item.splitlines():
            line = line.strip().strip('"').strip("'").strip()
            if not line:
                continue
            
            # 再处理同行内多个 PDF 被空格隔开的情况
            if ".pdf " in line.lower() or ".pdf\"" in line.lower():
                parts = line.replace(".pdf ", ".pdf|").replace(".PDF ", ".PDF|").split("|")
                for p in parts:
                    clean_p = p.strip().strip('"').strip("'").strip()
                    if clean_p:
                        pdf_tasks.append(clean_p)
            else:
                pdf_tasks.append(line)

    # 3. 解析输入类型并生成真正的任务池
    final_tasks = []
    for target in pdf_tasks:
        if os.path.isdir(target):
            print(f"📂 识别为【文件夹】，正在提取内部 PDF...")
            for file in os.listdir(target):
                if file.lower().endswith(".pdf"):
                    final_tasks.append(os.path.join(target, file))
                    
        elif target.lower().endswith(".txt") and os.path.isfile(target):
            print(f"📝 识别为【TXT 列表】，正在读取文献路径...")
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    clean_path = line.strip().strip('"').strip("'")
                    if clean_path.lower().endswith(".pdf") and os.path.isfile(clean_path):
                        final_tasks.append(clean_path)
                        
        elif target.lower().endswith(".pdf") and os.path.isfile(target):
            final_tasks.append(target)
            
        else:
            print(f"⚠️ 忽略无效路径或文件不存在 -> {target}")

    # 4. 去除重复文献，防止二次提交
    final_tasks = list(dict.fromkeys(final_tasks))

    # 5. 开始批量执行
    total_files = len(final_tasks)
    if total_files == 0:
        print("\n📭 没有找到任何有效的 PDF 任务，程序退出。")
        exit()

    print(f"\n🔥 共提取到 {total_files} 篇待解析文献。准备开工！\n" + "="*50)

    for index, pdf_path in enumerate(final_tasks, start=1):
        print(f"\n▶️ [进度 {index}/{total_files}] 正在处理文献: {os.path.basename(pdf_path)}")
        save_to_obsidian(pdf_path)
        
        if index < total_files:
            print("☕ 休息 3 秒钟后继续下一篇，防止触发服务器流控...")
            time.sleep(3)

    print("\n" + "="*50)
    print("🏆 批量任务全部完成！去 Obsidian 里检阅你的文献大军吧！")