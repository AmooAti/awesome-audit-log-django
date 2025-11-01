import logging
from datetime import datetime

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def example_periodic_task():
    logger.info("Periodic task executed")

    from products.models import Category

    try:
        category = Category.objects.first()
        if category:
            original_name = category.name
            category.name = (
                f"{category.name} (checked at {datetime.now().strftime('%H:%M:%S')})"
            )
            category.save()
            logger.info(f"Updated category: {original_name} -> {category.name}")
            return f"Updated category {category.id}"
        else:
            logger.warning("No categories found in database")
            return "No categories found"
    except Exception as e:
        logger.error(f"Error in periodic task: {e}", exc_info=True)
        raise


@shared_task
def update_product_quantity(product_id: int = None, new_quantity: int = 0):
    logger.info(
        f"update_product_quantity called: product_id={product_id}, new_quantity={new_quantity}"
    )

    from products.models import Product

    try:
        if product_id:
            product = Product.objects.get(id=product_id)
        else:
            product = Product.objects.first()

        if product:
            old_quantity = product.quantity
            product.quantity = new_quantity if new_quantity else old_quantity + 1
            product.save()
            logger.info(
                f"Updated product {product.name} quantity from {old_quantity} to {product.quantity}"
            )
            return {
                "product_id": product.id,
                "old_quantity": old_quantity,
                "new_quantity": product.quantity,
            }
        else:
            logger.warning("No products found in database")
            return None
    except Product.DoesNotExist:
        logger.error(f"Product with id {product_id} not found")
        raise
    except Exception as e:
        logger.error(f"Error updating product quantity: {e}", exc_info=True)
        raise
