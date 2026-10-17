# Integration tests

真实外部集成测试必须由显式环境变量启用；没有外部服务或本地保存产物时会明确跳过，不能用
Mock 结果冒充真实验证。

Elasticsearch Task 3 持久化测试：

```bash
ELASTICSEARCH_URL=http://localhost:9200 \
  python -m pytest tests/integration/test_keyword_retrieval_elasticsearch.py -q
```

测试只创建带随机 UUID 的 `engineering-rag-task3-test-*` 索引，并在结束时删除该测试索引。
其他 Parser/Chunking 真实回放测试的启用条件见各测试文件和模块文档。

