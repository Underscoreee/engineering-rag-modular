# File Store

`engineering_rag.infrastructure.file_store.api.FileStore` 声明 `put(Path | BinaryIO, media_type) -> FileRef`、`read(...) ->` 二进制上下文管理器、`exists` 和 `delete`。URI 是持久身份，`Path` 仅表示调用方本地输入，bytes 通过流传递。put 应按实现声明幂等策略；delete 有副作用且不存在时返回 `False`。Task 0 无存储后端。

