from django.urls import path

from tests.fixtures.testapp import views

urlpatterns = [
    path("api/widgets/create/", views.create_widget, name="api_widgets_create"),
]
