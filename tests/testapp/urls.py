from django.urls import path

from tests.testapp import views

urlpatterns = [
    path("api/widgets/create/", views.create_widget, name="api_widgets_create"),
]