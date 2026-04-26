from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posts", "0008_post_is_pinned"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="parent_post",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="replies",
                to="posts.post",
            ),
        ),
        migrations.AddIndex(
            model_name="post",
            index=models.Index(fields=["parent_post", "-created_at"], name="posts_post_parent__f0ee0c_idx"),
        ),
    ]
