# 本地图片与资源

所有图片保存在输出套件的 `assets/` 中，HTML 和 `suite.json` 均以 `assets/<文件名>` 相对引用，ZIP 包携带全部本地素材。不依赖图床或外部图片地址。

解析阶段按内容 SHA-256 去重并命名。支持 HTML 的 img/srcset、CSS url、内联 SVG image href 和 data URI；原来源中的 HTTP(S) 资源会下载到本地。下载失败或源文件缺失直接报错。PPT 的 media 全部导出，包括母版引用的媒体。

外置 SVG 若引用其他文件，应先内嵌为自包含 SVG，确保单个素材文件能够完整显示。装饰 SVG 保留矢量形式。字体等 CSS 资源也保存在 assets 中。

制作模板时将解析目录中的 assets 复制到套件目录，然后使用对应相对路径。仅有片段标识的引用（例如 SVG `#gradient`）保持不变；外部 SVG 的 `assets/icon.svg#symbol` 也保留片段。

```text
python "<skill>/scripts/package_suite.py" --suite-dir "output/my-style" --name "我的套件"
```

打包器检查所有图片/样式资源引用，仅接受套件 assets 内实际存在的文件；外部 URL、data URI、绝对路径或逃逸到套件外部的路径均报错，应回到解析步骤将资源本地化。打包阶段不访问网络。

`assets-manifest.json` 每项包含 `path`（相对路径）、`sha256`（内容摘要）。重复引用仅记录一次；每次打包重新生成清单，不沿用历史外部地址。未被模板引用的原始素材仍保留在 assets 和 ZIP 中。

交付时需保持 HTML 与 assets 的相对层级。若消费端只保存 HTML 字符串，需由消费端提供相应的本地资源解析或文件服务；本 Skill 不改变图片的相对地址。
