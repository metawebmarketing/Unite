from django.conf import settings
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0015_linkpreviewcache_image_url"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="mediaattachment",
            name="hls_manifest_url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="mediaattachment",
            name="media_bytes",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="mediaattachment",
            name="processing_status",
            field=models.CharField(default="ready", max_length=16),
        ),
        migrations.AddField(
            model_name="mediaattachment",
            name="thumbnail_url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.CreateModel(
            name="UploadedMediaAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("media_type", models.CharField(choices=[("image", "Image"), ("video", "Video")], max_length=16)),
                ("media_url", models.URLField(unique=True, validators=[django.core.validators.MinLengthValidator(10)])),
                ("thumbnail_url", models.URLField(blank=True, default="")),
                ("hls_manifest_url", models.URLField(blank=True, default="")),
                ("media_bytes", models.PositiveBigIntegerField(default=0)),
                (
                    "processing_status",
                    models.CharField(
                        choices=[("processing", "Processing"), ("ready", "Ready"), ("failed", "Failed")],
                        default="ready",
                        max_length=16,
                    ),
                ),
                ("storage_mode", models.CharField(blank=True, default="", max_length=16)),
                ("storage_saved_name", models.CharField(blank=True, default="", max_length=500)),
                ("thumbnail_saved_name", models.CharField(blank=True, default="", max_length=500)),
                ("hls_manifest_saved_name", models.CharField(blank=True, default="", max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="uploaded_media_assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="uploadedmediaasset",
            index=models.Index(fields=["user", "media_type", "-created_at"], name="posts_uploa_user_id_7096d4_idx"),
        ),
        migrations.AddIndex(
            model_name="uploadedmediaasset",
            index=models.Index(
                fields=["user", "processing_status", "-created_at"],
                name="posts_uploa_user_id_89f466_idx",
            ),
        ),
    ]
