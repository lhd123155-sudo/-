
from pathlib import Path
from collections import Counter
from hashlib import sha256
import re

import numpy as np
import pandas as pd
import plotly.express as plotly_express
import streamlit as st
from PIL import Image, ImageDraw


# =========================================================
# 1. 页面配置
# =========================================================

st.set_page_config(
    page_title="超级马里奥关卡分析平台",
    page_icon="🎮",
    layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = (
    BASE_DIR
    / "TheVGLC-master"
    / "Super Mario Bros"
    / "Original"
)

st.title("🎮 超级马里奥兄弟关卡分析平台")
st.caption(
    "Video Game Level Corpus · Super Mario Bros."
)
st.divider()


# =========================================================
# 2. 扫描关卡图片
# =========================================================

@st.cache_data
def scan_maps(folder):
    folder = Path(folder)
    results = []

    if not folder.exists():
        return results

    for file in folder.glob("*.png"):
        match = re.fullmatch(
            r"mario-(\d+)-(\d+)",
            file.stem,
            flags=re.IGNORECASE
        )

        if match is None:
            continue

        world = int(match.group(1))
        level = int(match.group(2))

        results.append({
            "世界": world,
            "关卡序号": level,
            "关卡编号": f"{world}-{level}",
            "文件名": file.name,
            "路径": str(file)
        })

    results.sort(
        key=lambda item: (
            item["世界"],
            item["关卡序号"]
        )
    )

    return results


maps = scan_maps(DATA_DIR)

if not maps:
    st.error(
        "没有找到关卡图片，请确认数据目录是否正确："
    )
    st.code(str(DATA_DIR))
    st.stop()

all_levels_df = pd.DataFrame(maps)


# =========================================================
# 3. 侧边栏设置
# =========================================================

with st.sidebar:
    st.header("⚙️ 数据设置")

    st.caption("当前数据目录")
    st.code(str(DATA_DIR), language=None)

    available_worlds = sorted(
        all_levels_df["世界"].unique().tolist()
    )

    selected_world = st.selectbox(
        "选择世界",
        options=available_worlds,
        index=0
    )

    current_world_df = all_levels_df[
        all_levels_df["世界"] == selected_world
    ]

    available_levels = current_world_df[
        "关卡编号"
    ].tolist()

    selected_level = st.selectbox(
        "选择关卡",
        options=available_levels
    )

    tile_size = st.select_slider(
        "图块尺寸（像素）",
        options=[8, 16, 32],
        value=16
    )

    show_grid = st.checkbox(
        "显示原图网格线",
        value=True
    )

    show_tile_ids = st.checkbox(
        "显示图块编号",
        value=False
    )

    st.divider()

    st.caption(
        "提示：切换图块尺寸后，图块统计结果也会改变。"
    )


selected_row = all_levels_df[
    all_levels_df["关卡编号"] == selected_level
].iloc[0]

image_path = Path(selected_row["路径"])


# =========================================================
# 4. 读取图片
# =========================================================

@st.cache_data
def load_rgb_array(path):
    with Image.open(path) as image:
        return np.asarray(
            image.convert("RGB")
        ).copy()


@st.cache_data
def analyze_map(path, size):
    arr = load_rgb_array(path)

    height, width, _ = arr.shape

    cols = width // size
    rows = height // size

    if rows == 0 or cols == 0:
        raise ValueError(
            "图块尺寸大于地图尺寸，无法完成网格划分。"
        )

    # 只分析能够完整切分的区域
    usable_width = cols * size
    usable_height = rows * size

    usable_arr = arr[
        :usable_height,
        :usable_width
    ]

    # 形状：
    # 地图行数 × 地图列数 × 图块高度 × 图块宽度 × RGB
    tiles = usable_arr.reshape(
        rows,
        size,
        cols,
        size,
        3
    ).transpose(
        0, 2, 1, 3, 4
    )

    fingerprints = []
    representatives = {}
    counts = Counter()

    for row_index in range(rows):
        for col_index in range(cols):
            tile = tiles[
                row_index,
                col_index
            ].copy()

            fingerprint = sha256(
                tile.tobytes()
            ).hexdigest()

            fingerprints.append(fingerprint)
            counts[fingerprint] += 1

            if fingerprint not in representatives:
                representatives[fingerprint] = tile

    # 常见图块排在前面
    ordered_fingerprints = [
        fingerprint
        for fingerprint, _ in counts.most_common()
    ]

    fingerprint_to_id = {
        fingerprint: index + 1
        for index, fingerprint
        in enumerate(ordered_fingerprints)
    }

    tile_map = np.asarray([
        fingerprint_to_id[fingerprint]
        for fingerprint in fingerprints
    ]).reshape(rows, cols)

    tile_info = []

    for fingerprint in ordered_fingerprints:
        tile_id = fingerprint_to_id[fingerprint]
        count = counts[fingerprint]

        tile_info.append({
            "图块ID": tile_id,
            "出现次数": count,
            "占比(%)": round(
                count / (rows * cols) * 100,
                2
            ),
            "图像": representatives[fingerprint]
        })

    # 整张图的精确颜色统计
    color_counts = Counter(
        map(
            tuple,
            arr.reshape(-1, 3).tolist()
        )
    )

    color_info = []

    for color, count in color_counts.most_common(15):
        color_info.append({
            "颜色": "#{:02X}{:02X}{:02X}".format(
                *color
            ),
            "RGB": str(color),
            "像素数": count,
            "占比(%)": round(
                count / (width * height) * 100,
                2
            )
        })

    return {
        "array": arr,
        "width": width,
        "height": height,
        "rows": rows,
        "cols": cols,
        "tile_map": tile_map,
        "tile_info": tile_info,
        "color_info": color_info,
        "remainder_x": width - usable_width,
        "remainder_y": height - usable_height
    }


try:
    data = analyze_map(
        str(image_path),
        tile_size
    )
except Exception as error:
    st.error(f"地图分析失败：{error}")
    st.stop()


arr = data["array"]
tile_map = data["tile_map"]
tile_info = data["tile_info"]

width = data["width"]
height = data["height"]
rows = data["rows"]
cols = data["cols"]

tile_total = rows * cols
unique_tiles = len(tile_info)


# =========================================================
# 5. 数据集概览
# =========================================================

st.header("一、数据集与关卡概览")

overview_columns = st.columns(4)

overview_columns[0].metric(
    "关卡图片数量",
    len(all_levels_df)
)

overview_columns[1].metric(
    "包含世界数量",
    all_levels_df["世界"].nunique()
)

overview_columns[2].metric(
    "当前地图列数",
    cols
)

overview_columns[3].metric(
    "当前地图行数",
    rows
)

detail_columns = st.columns(4)

detail_columns[0].metric(
    "图块总数",
    f"{tile_total:,}"
)

detail_columns[1].metric(
    "不同图块类型",
    unique_tiles
)

detail_columns[2].metric(
    "最常见图块占比",
    f"{tile_info[0]['占比(%)']:.1f}%"
)

detail_columns[3].metric(
    "图块尺寸",
    f"{tile_size} × {tile_size}"
)

st.info(
    "图块通过像素完全一致进行分类。"
    "图块编号仅表示图像类别，不代表地面、敌人或管道等语义类别。"
)


# =========================================================
# 6. 关卡地图浏览器
# =========================================================

st.header("二、关卡地图浏览器")
st.subheader(f"世界 {selected_level}")

left_column, right_column = st.columns(
    [3, 1]
)

with left_column:
    display_image = Image.fromarray(arr.copy())

    if show_grid or show_tile_ids:
        draw = ImageDraw.Draw(display_image)

        usable_width = cols * tile_size
        usable_height = rows * tile_size

        if show_grid:
            # 注意：使用 pixel_x / pixel_y，
            # 避免覆盖 Plotly 模块名称。
            for pixel_x in range(
                0,
                usable_width + 1,
                tile_size
            ):
                draw.line(
                    [
                        (pixel_x, 0),
                        (pixel_x, usable_height)
                    ],
                    fill=(255, 70, 70),
                    width=1
                )

            for pixel_y in range(
                0,
                usable_height + 1,
                tile_size
            ):
                draw.line(
                    [
                        (0, pixel_y),
                        (usable_width, pixel_y)
                    ],
                    fill=(255, 70, 70),
                    width=1
                )

        if show_tile_ids:
            for row_index in range(rows):
                for col_index in range(cols):
                    tile_id = int(
                        tile_map[row_index, col_index]
                    )

                    draw.text(
                        (
                            col_index * tile_size + 1,
                            row_index * tile_size + 1
                        ),
                        str(tile_id),
                        fill=(255, 0, 0),
                        stroke_width=0
                    )

    st.image(
        display_image,
        caption=selected_row["文件名"],
        use_container_width=True
    )

with right_column:
    st.markdown("**图片属性**")

    st.write(f"宽度：{width} px")
    st.write(f"高度：{height} px")
    st.write(f"像素总数：{width * height:,}")

    st.write(
        f"图块行列：{rows} × {cols}"
    )

    st.write(f"不同图块：{unique_tiles}")

    st.write(
        f"文件大小："
        f"{image_path.stat().st_size / 1024:.2f} KB"
    )

    if data["remainder_x"] or data["remainder_y"]:
        st.warning(
            "地图边缘存在未纳入完整网格的像素："
            f"横向 {data['remainder_x']} px，"
            f"纵向 {data['remainder_y']} px。"
        )


# =========================================================
# 7. 图块类型与频次分析
# =========================================================

st.header("三、图块类型分析")

tile_df = pd.DataFrame([
    {
        "图块ID": item["图块ID"],
        "出现次数": item["出现次数"],
        "占比(%)": item["占比(%)"]
    }
    for item in tile_info
])

max_display = min(30, unique_tiles)

default_display = min(15, max_display)

display_count = st.slider(
    "显示出现次数最多的图块类型",
    min_value=1,
    max_value=max_display,
    value=default_display
)

top_tiles_df = tile_df.head(display_count)

frequency_fig = plotly_express.bar(
    top_tiles_df,
    x="图块ID",
    y="出现次数",
    hover_data=["占比(%)"],
    title="常见图块出现频次"
)

frequency_fig.update_layout(
    xaxis_title="图块ID",
    yaxis_title="出现次数"
)

st.plotly_chart(
    frequency_fig,
    use_container_width=True
)

st.dataframe(
    tile_df,
    use_container_width=True,
    hide_index=True
)

st.download_button(
    "下载图块统计 CSV",
    data=tile_df.to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name=(
        f"mario_{selected_level}_tile_statistics.csv"
    ),
    mime="text/csv"
)


# =========================================================
# 8. 图块图鉴
# =========================================================

st.header("四、图块图鉴")

st.caption(
    "图块按出现频次排序。相同像素图案使用相同编号；"
    "编号只在当前关卡和当前图块尺寸下有效。"
)

gallery_count = min(30, unique_tiles)

gallery_columns = st.columns(5)

for index, item in enumerate(
    tile_info[:gallery_count]
):
    with gallery_columns[index % 5]:
        tile_image = Image.fromarray(
            item["图像"]
        )

        enlarged_image = tile_image.resize(
            (
                tile_size * 4,
                tile_size * 4
            ),
            Image.Resampling.NEAREST
        )

        st.image(
            enlarged_image,
            caption=(
                f"图块 {item['图块ID']}｜"
                f"{item['出现次数']} 次"
            ),
            use_container_width=True
        )


# =========================================================
# 8.5 图块人工标注与持久化
# =========================================================

import json

st.header("图块人工标注")

st.write(
    "为图块指定实际类别。标注会保存到项目目录中的 "
    "tile_labels.json，后续可用于统计地形结构。"
)

LABEL_FILE = BASE_DIR / "tile_labels.json"

TILE_CATEGORIES = [
    "未标注",
    "地面",
    "砖块",
    "问号方块",
    "管道",
    "敌人",
    "可交互物品",
    "背景",
    "装饰",
    "其他"
]


def load_tile_labels():
    if not LABEL_FILE.exists():
        return {}

    try:
        with open(
            LABEL_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            result = json.load(file)

        if isinstance(result, dict):
            return result

        return {}

    except (OSError, json.JSONDecodeError):
        return {}


def save_tile_labels(labels):
    temporary_file = LABEL_FILE.with_suffix(".tmp")

    with open(
        temporary_file,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            labels,
            file,
            ensure_ascii=False,
            indent=2
        )

    temporary_file.replace(LABEL_FILE)


tile_labels = load_tile_labels()

# 用图块真实像素生成稳定指纹。
# 不依赖图块ID，因此切换关卡后可匹配相同图案。
current_tile_records = []

for item in tile_info:
    tile_array = np.asarray(
        item["图像"],
        dtype=np.uint8
    )

    tile_fingerprint = sha256(
        tile_array.tobytes()
    ).hexdigest()

    current_tile_records.append({
        "图块ID": item["图块ID"],
        "指纹": tile_fingerprint,
        "出现次数": item["出现次数"],
        "占比(%)": item["占比(%)"],
        "图像": item["图像"]
    })

# 默认先显示未标注图块
unlabeled_records = [
    record
    for record in current_tile_records
    if record["指纹"] not in tile_labels
    or tile_labels[record["指纹"]].get("类别", "未标注")
    == "未标注"
]

label_mode = st.radio(
    "图块筛选方式",
    [
        "只看未标注图块",
        "查看当前关卡全部图块"
    ],
    horizontal=True
)

if label_mode == "只看未标注图块":
    selectable_records = unlabeled_records
else:
    selectable_records = current_tile_records

if not selectable_records:
    st.success(
        "当前关卡没有待标注图块。"
        "可以切换到“查看当前关卡全部图块”修改已有类别。"
    )
else:
    record_options = {
        (
            f"图块 {record['图块ID']}｜"
            f"出现 {record['出现次数']} 次"
        ): record
        for record in selectable_records
    }

    selected_record_name = st.selectbox(
        "选择要标注的图块",
        options=list(record_options.keys())
    )

    selected_record = record_options[
        selected_record_name
    ]

    selected_fingerprint = selected_record["指纹"]

    old_label = tile_labels.get(
        selected_fingerprint,
        {}
    ).get("类别", "未标注")

    if old_label not in TILE_CATEGORIES:
        old_label = "其他"

    label_left, label_right = st.columns([1, 2])

    with label_left:
        enlarged_tile = Image.fromarray(
            selected_record["图像"]
        ).resize(
            (
                tile_size * 8,
                tile_size * 8
            ),
            Image.Resampling.NEAREST
        )

        st.image(
            enlarged_tile,
            caption=(
                f"图块 {selected_record['图块ID']}"
            ),
            use_container_width=True
        )

        st.metric(
            "当前关卡出现次数",
            selected_record["出现次数"]
        )

    with label_right:
        new_category = st.selectbox(
            "选择图块类别",
            options=TILE_CATEGORIES,
            index=TILE_CATEGORIES.index(old_label),
            key=f"category_{selected_fingerprint}"
        )

        old_note = tile_labels.get(
            selected_fingerprint,
            {}
        ).get("备注", "")

        new_note = st.text_input(
            "备注（可选）",
            value=old_note,
            key=f"note_{selected_fingerprint}",
            placeholder="例如：普通地面、管道顶部"
        )

        if st.button(
            "保存当前图块标注",
            type="primary"
        ):
            tile_labels[selected_fingerprint] = {
                "类别": new_category,
                "备注": new_note,
                "图块尺寸": tile_size,
                "图像指纹": selected_fingerprint
            }

            save_tile_labels(tile_labels)

            st.success(
                f"已保存：图块 "
                f"{selected_record['图块ID']} → {new_category}"
            )

            st.rerun()

# 标注进度
labeled_count = sum(
    1
    for record in current_tile_records
    if record["指纹"] in tile_labels
    and tile_labels[record["指纹"]].get("类别", "未标注")
    != "未标注"
)

total_current_tiles = len(current_tile_records)

progress_ratio = (
    labeled_count / total_current_tiles
    if total_current_tiles
    else 0
)

st.subheader("当前关卡标注进度")

progress_col1, progress_col2 = st.columns(2)

progress_col1.metric(
    "已标注图块类型",
    f"{labeled_count} / {total_current_tiles}"
)

progress_col2.metric(
    "标注完成率",
    f"{progress_ratio * 100:.1f}%"
)

st.progress(progress_ratio)

# 当前关卡的标注统计
label_summary_rows = []

for record in current_tile_records:
    saved_label = tile_labels.get(
        record["指纹"],
        {}
    ).get("类别", "未标注")

    label_summary_rows.append({
        "图块ID": record["图块ID"],
        "类别": saved_label,
        "出现次数": record["出现次数"],
        "占比(%)": record["占比(%)"]
    })

label_summary_df = pd.DataFrame(
    label_summary_rows
)

st.subheader("当前关卡标注清单")

st.dataframe(
    label_summary_df,
    use_container_width=True,
    hide_index=True
)

st.download_button(
    "导出当前关卡标注清单",
    data=label_summary_df.to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name=f"mario_{selected_level}_labels.csv",
    mime="text/csv"
)

# =========================================================
# 9. 图块分布图
# =========================================================

st.header("五、地图结构分布")

st.caption(
    "颜色表示图块ID。此图用于查看不同图块在地图中的空间分布，"
    "尚未将图块自动解释为具体游戏物体。"
)

map_fig = plotly_express.imshow(
    tile_map,
    aspect="auto",
    origin="upper",
    labels={
        "x": "地图列",
        "y": "地图行",
        "color": "图块ID"
    },
    title=f"世界 {selected_level} 图块分布"
)

map_fig.update_layout(height=450)

st.plotly_chart(
    map_fig,
    use_container_width=True
)


# =========================================================
# 10. 初步结构复杂度分析
# =========================================================

st.header("六、初步结构复杂度分析")

st.write(
    "本模块使用图块多样性、相邻格子变化和底部候选区域"
    "建立探索性指标。该评分不是经过玩家数据验证的难度模型。"
)

# 10.1 水平和垂直相邻格子的变化比例

horizontal_changes = (
    int(np.sum(
        tile_map[:, 1:] != tile_map[:, :-1]
    ))
    if cols > 1 else 0
)

vertical_changes = (
    int(np.sum(
        tile_map[1:, :] != tile_map[:-1, :]
    ))
    if rows > 1 else 0
)

horizontal_edges = rows * max(cols - 1, 0)
vertical_edges = max(rows - 1, 0) * cols

total_edges = horizontal_edges + vertical_edges

change_ratio = (
    (horizontal_changes + vertical_changes)
    / total_edges
    if total_edges > 0 else 0
)

# 10.2 图块多样性指标
diversity_score = min(
    unique_tiles / 20,
    1.0
) * 100


# 10.3 选择可能的背景图块

tile_options = {
    (
        f"图块 {item['图块ID']} "
        f"（出现 {item['出现次数']} 次）"
    ): item["图块ID"]
    for item in tile_info
}

default_background_label = next(
    iter(tile_options)
)

selected_background_label = st.selectbox(
    "选择一个可能代表背景或空白区域的图块",
    options=list(tile_options.keys()),
    index=0,
    help=(
        "请参考图块图鉴进行选择。"
        "最常见图块不一定是背景，可以手动更改。"
    )
)

background_id = tile_options[
    selected_background_label
]


# 10.4 检查地图底部的连续区域

bottom_rows_count = min(2, rows)

bottom_map = tile_map[
    -bottom_rows_count:,
    :
]

background_mask = (
    bottom_map == background_id
)

candidate_runs = []

for local_row, line in enumerate(background_mask):
    run_start = None

    for col_index in range(cols + 1):
        is_background = (
            col_index < cols
            and bool(line[col_index])
        )

        if is_background and run_start is None:
            run_start = col_index

        elif not is_background and run_start is not None:
            run_length = col_index - run_start

            if run_length >= 2:
                candidate_runs.append({
                    "地图行": (
                        rows
                        - bottom_rows_count
                        + local_row
                        + 1
                    ),
                    "起始列": run_start + 1,
                    "结束列": col_index,
                    "连续长度（格）": run_length
                })

            run_start = None


runs_df = pd.DataFrame(
    candidate_runs,
    columns=[
        "地图行",
        "起始列",
        "结束列",
        "连续长度（格）"
    ]
)

candidate_cells = sum(
    item["连续长度（格）"]
    for item in candidate_runs
)

candidate_area_ratio = (
    candidate_cells
    / max(bottom_rows_count * cols, 1)
)

transition_score = change_ratio * 100

gap_score = min(
    candidate_area_ratio * 2,
    1.0
) * 100

complexity_score = (
    diversity_score * 0.35
    + transition_score * 0.35
    + gap_score * 0.30
)

score_columns = st.columns(4)

score_columns[0].metric(
    "图块多样性指标",
    f"{diversity_score:.1f}/100"
)

score_columns[1].metric(
    "相邻变化比例",
    f"{transition_score:.1f}%"
)

score_columns[2].metric(
    "底部候选区域比例",
    f"{candidate_area_ratio * 100:.1f}%"
)

score_columns[3].metric(
    "探索性复杂度评分",
    f"{complexity_score:.1f}/100"
)

st.progress(
    int(round(complexity_score))
)

st.warning(
    "注意：底部连续背景区域不一定是坑洞。"
    "图块多样性也不必然意味着关卡更难。"
    "当前评分只用于探索和比较地图结构，不能解释为死亡率。"
)

st.markdown("**底部连续区域候选列表**")

if runs_df.empty:
    st.info(
        "当前设置下没有发现长度至少为 2 格的连续候选区域。"
    )
else:
    st.dataframe(
        runs_df,
        use_container_width=True,
        hide_index=True
    )

st.download_button(
    "下载候选区域 CSV",
    data=runs_df.to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name=(
        f"mario_{selected_level}_candidate_regions.csv"
    ),
    mime="text/csv"
)


# =========================================================
# 11. 原图颜色分析
# =========================================================

st.header("七、图像颜色分析")

st.caption(
    "统计整张图片中出现频率最高的精确 RGB 颜色。"
    "颜色数量与地形类别数量并不相同。"
)

color_df = pd.DataFrame(
    data["color_info"]
)

if not color_df.empty:
    st.dataframe(
        color_df,
        use_container_width=True,
        hide_index=True
    )

    color_fig = plotly_express.bar(
        color_df,
        x="颜色",
        y="像素数",
        hover_data=["RGB", "占比(%)"],
        title="出现频率最高的 15 种颜色"
    )

    color_fig.update_layout(
        xaxis_title="颜色",
        yaxis_title="像素数"
    )

    st.plotly_chart(
        color_fig,
        use_container_width=True
    )


# =========================================================
# 12. 全部关卡数据对比
# =========================================================

st.header("八、全部关卡数据")

@st.cache_data
def build_overview(folder, records):
    result = []

    for record in records:
        file_path = Path(record["路径"])

        try:
            with Image.open(file_path) as image:
                image_width, image_height = image.size

            result.append({
                "世界": record["世界"],
                "关卡": record["关卡编号"],
                "宽度(px)": image_width,
                "高度(px)": image_height,
                "文件大小(KB)": round(
                    file_path.stat().st_size / 1024,
                    2
                )
            })

        except (OSError, ValueError):
            continue

    return pd.DataFrame(result)


overview_df = build_overview(
    str(DATA_DIR),
    maps
)

selected_worlds = st.multiselect(
    "筛选世界",
    options=sorted(
        overview_df["世界"].unique().tolist()
    ),
    default=sorted(
        overview_df["世界"].unique().tolist()
    )
)

filtered_df = overview_df[
    overview_df["世界"].isin(selected_worlds)
].copy()

st.dataframe(
    filtered_df,
    use_container_width=True,
    hide_index=True
)

if not filtered_df.empty:
    width_fig = plotly_express.bar(
        filtered_df,
        x="关卡",
        y="宽度(px)",
        color="世界",
        title="各关卡地图宽度对比"
    )

    st.plotly_chart(
        width_fig,
        use_container_width=True
    )

    height_fig = plotly_express.bar(
        filtered_df,
        x="关卡",
        y="高度(px)",
        color="世界",
        title="各关卡地图高度对比"
    )

    st.plotly_chart(
        height_fig,
        use_container_width=True
    )

st.download_button(
    "下载全部关卡属性 CSV",
    data=filtered_df.to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name="mario_level_overview.csv",
    mime="text/csv"
)


# =========================================================
# 13. 方法说明
# =========================================================

st.divider()

st.header("九、数据与方法说明")

st.markdown("""
**数据来源**

Video Game Level Corpus（VGLC），当前使用其中的
Super Mario Bros Original 关卡图片。

**图块分类**

程序按照固定尺寸切分地图，并比较每个图块的 RGB 像素。
像素完全相同的图块会归为同一类。

**结构统计**

统计图块出现频次、图块空间分布、相邻图块变化比例，
并探索地图底部可能存在的连续区域。

**当前局限**

- 图块编号不代表实际物体类别。
- 图块变化不一定意味着障碍或危险。
- 底部候选区域不一定是坑洞。
- 当前复杂度评分是人为设置的探索性指标，
  未经过真实玩家通关或死亡数据验证。

**后续改进方向**

1. 建立图块语义标注，识别地面、砖块、管道等类别。
2. 统计平台间距、候选坑洞长度和障碍物分布。
3. 接入正在运行的游戏窗口，记录真实死亡、重生和进度。
4. 将真实玩家事件与关卡结构关联，进一步分析难度。
""")

st.caption(
    "超级马里奥兄弟关卡分析平台 · 结构分析实验版"
)
