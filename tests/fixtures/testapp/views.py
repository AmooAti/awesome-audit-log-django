import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from tests.fixtures.testapp.models import Widget


@require_POST
def create_widget(request):
    data = json.loads(request.body or "{}")
    w = Widget.objects.create(name=data.get("name", "n/a"), qty=data.get("qty", 1))
    return JsonResponse({"id": w.pk})
