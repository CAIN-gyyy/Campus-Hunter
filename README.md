# CampusHunter 北🍐二课帮助赤石小工具

CampusHunter 是一款基于 Python 开发的查看二课分数，并且帮助报名二课活动的小工具（通过 `token.txt` 文件读取），并采用了 Monokai Pro 的美观 UI 配色。该应用通过抓取 `/api/transcript/score` 接口数据并展示。
使用Claude开发。

## 功能介绍

- **外部 Token 支持**：首次运行自动生成提示，将认证 Token 存入本地的 `token.txt`，防止硬编码泄露，且便于编译成可执行文件后更新。
- **现代化 UI**：界面使用 Monokai Pro 色彩主题，视觉体验极佳。（这点设计欠缺，用户可根据自己喜好修改）
- **SSL 警告屏蔽**：修复了网络请求中的 SSL 证书异常警告，保证请求稳定执行。
- **自动抓取与刷新**：内置定时自动抓取机制。

## 运行与编译

你可以直接运行源代码：
```bash
python main.py
```

或者使用 PyInstaller 配合现有的 `main.spec` 编译出可执行文件：
```bash
pyinstaller main.spec
```

## 注意事项

由于第二课堂需要采用**wx小程序**的特殊性，token需要定时更换，需要使用工具**手动**抓包token
