import os
import time
import re
import requests
import zipfile
import io
import hashlib
import sys

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
# ⚠️ 必须替换为你官网上申请的真实 API Token！
TOKEN = "替换成你的MinerU的TOKEN" 

# 🚀 极简双模输入引擎：优先读取命令行参数，否则回退到手动输入
if len(sys.argv) > 1:
    raw_path = sys.argv[1]
    print(f"📥 [自动模式] 已接收到传入路径: {raw_path}")
else:
    print("💡 提示：你可以输入...\n  1. 单个 PDF 路径\n  2. 包含多个 PDF 的文件夹路径\n  3. 包含多个 PDF 路径的 TXT 文本文件路径")
    raw_path = input("👉 请在此处粘贴路径 (然后按回车): ")

INPUT_PATH = raw_path.strip('"').strip("'")

# 解析结果的保存目标位置
SAVE_DIR = r"H:\ObsidianVaults\Literature\文献笔记" #替换成你的Obisidian中的文献笔记保存路径

# V4 API 接口地址
BASE_URL = "https://mineru.net/api/v4"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# =====================================================================
# 模块 3：核心功能 - V4 批量接口上传与 VLM 激活
# =====================================================================
def parse_by_file_v4(file_path):
    file_name = os.path.basename(file_path)
    data_id = f"task_{int(time.time())}"

    print(f"🚀 [步骤 1] 正在申请 V4 安全通道 (激活 VLM 模型): {file_name}")
    data = {
        "files": [{"name": file_name, "data_id": data_id}],
        "model_version": "vlm"
    }
    
    try:
        resp = requests.post(f"{BASE_URL}/file-urls/batch", headers=HEADERS, json=data, proxies={"http": None, "https": None})
        if resp.status_code != 200:
            print(f"❌ 申请通道失败, HTTP: {resp.status_code}")
            return None
            
        result = resp.json()
        if result.get("code") != 0:
            print(f"❌ 获取上传链接失败: {result.get('msg')}")
            return None

        batch_id = result["data"]["batch_id"]
        upload_url = result["data"]["file_urls"][0]
        print(f"✅ V4 通道开启！批次号: {batch_id}")

    except Exception as e:
        print(f"❌ 网络请求异常: {e}")
        return None

    print(f"📤 [步骤 2] 正在将文献直传至云端...")
    try:
        with open(file_path, 'rb') as f:
            put_resp = requests.put(upload_url, data=f, proxies={"http": None, "https": None})
            if put_resp.status_code != 200:
                print(f"❌ 文件上传云端失败, HTTP {put_resp.status_code}")
                return None
    except Exception as e:
        print(f"❌ 上传过程异常: {e}")
        return None
        
    print("✅ 文件成功送达云端！")
    print("⏳ [步骤 3] VLM 视觉大模型(VLM) 正在逐页提取图表...")
    return poll_result_v4(batch_id, os.path.splitext(file_name)[0])

# =====================================================================
# 模块 4：轮询等待与 ZIP 数据包拆解 (极简版)
# =====================================================================
def poll_result_v4(batch_id, base_name, timeout=1200, interval=10):
    start = time.time() 
    query_url = f"{BASE_URL}/extract-results/batch/{batch_id}"
    
    while time.time() - start < timeout:
        try:
            resp = requests.get(query_url, headers=HEADERS, proxies={"http": None, "https": None})
            if resp.status_code != 200:
                print(f"❌ 查询进度接口报错 (HTTP {resp.status_code})。")
                return None
            result = resp.json()
            if result.get("code") != 0:
                print(f"❌ 查询状态报错: {result.get('msg')}")
                return None
            extract_results = result.get("data", {}).get("extract_result", [])
            if not extract_results:
                return None
            task_info = extract_results[0] 
            state = task_info.get("state")
            elapsed = int(time.time() - start)
            if state == "done":
                full_zip_url = task_info.get("full_zip_url")
                print(f"🎉 [{elapsed}s] VLM 解析彻底完成！")
                print(f"⬇️ [步骤 4] 正在下载云端 ZIP 数据包并在内存中拆解...")
                return download_and_extract_zip(full_zip_url)
            elif state == "failed":
                print(f"❌ 解析失败")
                return None
            else:
                pages = task_info.get("extract_progress", {}).get("extracted_pages", 0)
                total = task_info.get("extract_progress", {}).get("total_pages", "?")
                print(f"[{elapsed}s] 运转中 (状态: {state}, 进度: {pages}/{total} 页)...")
        except Exception as e:
            print(f"❌ 轮询异常: {e}")
        time.sleep(interval)
    return None

def download_and_extract_zip(zip_url):
    try:
        resp = requests.get(zip_url, proxies={"http": None, "https": None})
        if resp.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            md_filename = next((name for name in zf.namelist() if name.endswith('.md')), None)
            if not md_filename:
                return None
            md_text = zf.read(md_filename).decode('utf-8')
            # 清洗公式乱码
            md_text = md_text.replace('\x01', '+').replace('\x02', '-').replace('\x03', '×').replace('\x04', '÷').replace('Ã½', 'ý')
            
            # 💡 极简改造：ZIP 拆解只负责提取原数据和扩展名，不在这里命名
            images_raw = {}
            for name in zf.namelist():
                ext = os.path.splitext(name)[1].lower()
                if ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
                    # 保存 ZIP 内的原路径作为 Key，用于后续在 Markdown 里查找替换
                    images_raw[name] = {
                        "data": zf.read(name),
                        "ext": ext
                    }
            return md_text, images_raw
    except Exception as e:
        print(f"❌ 解析异常: {e}")
        return None

# =====================================================================
# 模块 5：系统入口与 Obsidian 整合 (真·极简Wikilinks)
# =====================================================================
def save_to_obsidian(pdf_file_path):
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    file_name = os.path.basename(pdf_file_path)
    base_name = os.path.splitext(file_name)[0]
    
    # 获取图片的 raw 数据和 MD 文本
    result_tuple = parse_by_file_v4(pdf_file_path)
    if not result_tuple:
        return
    md_text, images_raw = result_tuple
    
    # 💡 核心极简：根据 PDF 文件的完整路径生成一个独一无二的 6 位短哈希，作为图片前缀
    # 这样就算同一篇文献，换个 PDF 名字重新解析，图片前缀也会不一样，绝对防止冲突
    pdf_path_hash = hashlib.md5(pdf_file_path.encode('utf-8')).hexdigest()[:6]
    
    assets_dir = os.path.join(SAVE_DIR, "assets")
    if images_raw and not os.path.exists(assets_dir):
        os.makedirs(assets_dir)
    
    if images_raw:
        print(f"🖼️ [步骤 4.5] 成功抠出 {len(images_raw)} 张图表！正在使用极简模式 [PDF哈希-序号] 保存至本地...")
    
    url_to_obsidian_wikilink_map = {}
    # 💡 图片计数器，从 1 开始
    img_counter = 1
    
    for original_zip_path, img_info in images_raw.items():
        # 💡 构造极简文件名： 9a5a12-1.jpg
        local_img_name = f"{pdf_path_hash}-{img_counter}{img_info['ext']}"
        local_img_path = os.path.join(assets_dir, local_img_name)
        
        # 写入本地资产库
        with open(local_img_path, "wb") as f:
            f.write(img_info["data"])
            
        normalized_zip_path = original_zip_path.lstrip('./').lstrip('/')
        # 映射： ZIP内路径 -> Obsidian 极简双链代码
        url_to_obsidian_wikilink_map[normalized_zip_path] = f"![[{local_img_name}]]"
        img_counter += 1

    # 🔥 真·极简替换引擎：拦截传统标签并替换为极简双链
    md_pattern = r'(!\[.*?\]\(([\.\/]*.*?)\))' 
    html_pattern = r'(<img[^>]*?src=["\']([\.\/]*.*?)["\'][^>]*?>)' 
    
    if images_raw:
        print(f"🧹 [步骤 4.8] 正在精准拦截标准图片占位符，统一升级为最极简格式的 Obsidian 原生双链...")
        
    for full_tag, path in re.findall(md_pattern, md_text):
        normalized_path = path.lstrip('./').lstrip('/')
        if normalized_path in url_to_obsidian_wikilink_map:
            md_text = md_text.replace(full_tag, url_to_obsidian_wikilink_map[normalized_path])

    for full_tag, path in re.findall(html_pattern, md_text):
        normalized_path = path.lstrip('./').lstrip('/')
        if normalized_path in url_to_obsidian_wikilink_map:
            md_text = md_text.replace(full_tag, url_to_obsidian_wikilink_map[normalized_path])

    # ---------------------------------------------------------
    # 核心：生成带 YAML 头的最终笔记
    # ---------------------------------------------------------
    year_match = re.search(r'(19|20)\d{2}', base_name)
    year = year_match.group(0) if year_match else "未知年份"

    output_path = os.path.join(SAVE_DIR, f"{base_name}.md")

    yaml_frontmatter = f"""---
title: "{base_name}"
year: {year}
tags:
  - #文献笔记
  - #矿床学
  - #成因机制
status: 🟢已解析
---

"""
    with open(output_path, "w", encoding="utf-8") as md_file:
        md_file.write(yaml_frontmatter + md_text)

    print("-" * 40)
    print(f"🎯 任务大满贯！文件名已极简化，且 Obsidian 显示率 100%: {output_path}")

# =====================================================================
# 🚀 模块 6：批量任务调度器
# =====================================================================
if __name__ == "__main__":
    pdf_tasks = []

    if os.path.isdir(INPUT_PATH):
        print(f"\n📂 检测到文件夹输入，扫描中...")
        for file in os.listdir(INPUT_PATH):
            if file.lower().endswith(".pdf"):
                pdf_tasks.append(os.path.join(INPUT_PATH, file))
    elif os.path.isfile(INPUT_PATH) and INPUT_PATH.lower().endswith(".txt"):
        print(f"\n📝 检测到 TXT 列表，读取中...")
        with open(INPUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                clean_path = line.strip().strip('"').strip("'")
                if clean_path and os.path.isfile(clean_path) and clean_path.lower().endswith(".pdf"):
                    pdf_tasks.append(clean_path)
    elif os.path.isfile(INPUT_PATH) and INPUT_PATH.lower().endswith(".pdf"):
        print(f"\n📄 检测到单文件输入。")
        pdf_tasks.append(INPUT_PATH)
    else:
        print("\n❌ 错误：输入无效。")
        exit()

    total_files = len(pdf_tasks)
    if total_files == 0:
        print("📭 没有找到有效的 PDF 任务。")
        exit()

    print(f"🔥 共 {total_files} 篇文献。V4 极简离线版启动！\n" + "="*50)

    for index, pdf_path in enumerate(pdf_tasks, start=1):
        print(f"\n▶️ [进度 {index}/{total_files}] 处理文献: {os.path.basename(pdf_path)}")
        save_to_obsidian(pdf_path)
        
        if index < total_files:
            time.sleep(3) # ☕

    print("\n" + "="*50)
    print("🏆 批量任务完成！快去 Obsidian 看看那些原生双链渲染出来的极简图表吧！")