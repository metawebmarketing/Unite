from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posts", "0018_post_media_analysis_fields"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="post",
            index=models.Index(
                fields=["parent_post", "visibility", "-created_at", "-id"],
                name="posts_parent_vis_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="post",
            index=models.Index(
                fields=["author", "parent_post", "-is_pinned", "-created_at"],
                name="posts_author_parent_pinned_idx",
            ),
        ),
    ]
