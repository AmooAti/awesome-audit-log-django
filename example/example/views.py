from django.http import JsonResponse
from django.views import View

from .tasks import update_product_quantity


class UpdateProductQuantityView(View):
    def get(self, request):
        product_id = request.GET.get("product_id")
        new_quantity = request.GET.get("new_quantity")

        try:
            product_id = int(product_id) if product_id else None
            new_quantity = int(new_quantity) if new_quantity else None
        except (ValueError, TypeError):
            return JsonResponse(
                {"error": "Invalid product_id or new_quantity"}, status=400
            )

        task = update_product_quantity.delay(
            product_id=product_id, new_quantity=new_quantity
        )

        return JsonResponse(
            {
                "status": "success",
                "message": "Product quantity update task queued",
                "task_id": task.id,
            }
        )
