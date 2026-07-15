"""统一响应的 ModelViewSet 基类。

- list 走分页器，返回 { code, message, data:{ total, results ... } }
- retrieve / create / update / destroy 统一包 { code, message, data }
"""
from rest_framework import viewsets

from .response import api_response


class BaseModelViewSet(viewsets.ModelViewSet):
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return api_response(serializer.data, message="创建成功", status=201)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return api_response(serializer.data, message="更新成功")

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return api_response(message="删除成功")
