#!/usr/bin/env python
# -*- coding: utf-8 -*-
from collections import deque
from dataclasses import dataclass, field
from typing import TypedDict, List, Literal, Union, Optional, Dict, Sequence, Any

import tiktoken
from langchain_core.documents import Document as LangchainDocument
from pydantic import BaseModel, PrivateAttr
from pydantic.v1 import root_validator, Field
from tiktoken import Encoding

import settings


class Metadata(TypedDict):
    content: str
    summary: str
    title: str
    type: Literal['web_page', 'essay', 'wiki']
    keywords: str
    source: str
    query: str


class Document(LangchainDocument):
    metadata: Metadata
    page_content: Any

    @classmethod
    def create(cls, metadata: Metadata, page_content=None):
        if not page_content:
            for k in settings.PAGE_CONTENT_KEYS:
                if _v := metadata.get(k):
                    page_content = _v
                    break
        if page_content and len(page_content) > settings.MAX_CHUNK_SIZE:
            page_content = page_content[:settings.MAX_CHUNK_SIZE] + '...'
        assert page_content, f'Can not find {settings.PAGE_CONTENT_KEYS}'
        return cls(metadata=metadata, page_content=page_content)


Query = str
NodeDataType = Union[Document, Query]


@dataclass
class Node:
    data: NodeDataType
    parent: Optional['Node'] = None
    child_nodes: List['Node'] = field(default_factory=list)
    deleted: bool = False

    @property
    def node_type(self) -> Literal['Document', 'Query']:
        if isinstance(self.data, Document):
            return 'Document'
        return 'Query'

    def add_child_nodes(self, dataset: List[NodeDataType]):
        nodes = []
        for data in dataset:
            nodes.append(Node(data=data, parent=self))
        self.child_nodes.extend(nodes)

    def all_nodes(self) -> List['Node']:
        nodes = [self]
        for node in self.child_nodes:
            nodes.extend(node.all_nodes())
        return nodes

    def all_documents(self) -> List[Document]:
        nodes = self.all_nodes()
        return [node.data for node in nodes if node.node_type == 'Document' and node.deleted is False]

    def delete(self):
        self.deleted = True


class Tree(BaseModel):
    root: 'Node'
    tokens: int = field(default=0)
    leaf_nodes: deque[Node] = field(default_factory=deque)
    doc_node_num: int = field(default=0)
    embedding_model: str = 'gpt-3.5-turbo'
    _encoding: Optional[Encoding] = PrivateAttr(None)

    def model_post_init(self, __context) -> None:
        self._encoding = tiktoken.encoding_for_model(self.embedding_model)

    def add_nodes(self, parent: Node, dataset: List[NodeDataType]):
        if not isinstance(dataset, Sequence):
            dataset = [dataset]
        parent.add_child_nodes(dataset=dataset)
        documents = [data for data in dataset if isinstance(data, Document)]
        if documents:
            self.leaf_nodes.extendleft(parent.child_nodes)
            self.doc_node_num += len(documents)
            doc_texts = ''.join(doc.page_content for doc in documents)
            self.tokens += len(self._encoding.encode(doc_texts))
        else:
            # 右端优先被处理
            self.leaf_nodes.extend(parent.child_nodes)

    def all_nodes(self):
        return self.root.all_nodes()

    def all_documents(self) -> List[Document]:
        return self.root.all_documents()
