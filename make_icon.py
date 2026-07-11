# -*- coding: utf-8 -*-
"""生成软件图标:表示"文件分类"——彩色文件被归入文件夹。"""
from PIL import Image, ImageDraw

S = 256
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


# 背景圆角方块(蓝色渐变感,用实色+高光)
rounded(d, (8, 8, S - 8, S - 8), 46, (37, 99, 235, 255))       # 主蓝
rounded(d, (8, 8, S - 8, S // 2), 46, (59, 130, 246, 255))     # 顶部亮一点

# 三张彩色文件卡(从上方"落入"文件夹),带轻微旋转错落
cards = [
    ((70, 40, 150, 96), (250, 204, 21, 255)),   # 黄
    ((104, 30, 184, 86), (248, 113, 113, 255)),  # 红
    ((138, 44, 210, 100), (52, 211, 153, 255)),  # 绿
]
for (box, color) in cards:
    rounded(d, box, 10, (255, 255, 255, 255))
    inner = (box[0] + 6, box[1] + 6, box[2] - 6, box[3] - 6)
    rounded(d, inner, 7, color)
    # 文件上的横线(文字感)
    lx0, lx1 = inner[0] + 6, inner[2] - 6
    ly = inner[1] + 12
    d.line((lx0, ly, lx1, ly), fill=(255, 255, 255, 220), width=4)
    d.line((lx0, ly + 14, lx1 - 14, ly + 14), fill=(255, 255, 255, 180), width=4)

# 文件夹主体(白色),带一个后标签
# 文件夹后标签
rounded(d, (52, 120, 120, 150), 10, (219, 234, 254, 255))
# 文件夹主体
rounded(d, (48, 138, 208, 214), 18, (241, 245, 249, 255))
# 文件夹前板(略深,营造开口)
rounded(d, (48, 158, 208, 214), 18, (255, 255, 255, 255))
# 文件夹底部阴影线
d.line((60, 206, 196, 206), fill=(203, 213, 225, 255), width=3)

# 保存多尺寸 ico
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img.save('app.ico', sizes=sizes)
img.save('app.png')
print('icon saved: app.ico / app.png')
