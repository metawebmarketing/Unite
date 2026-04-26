from django.db.models import Count, Q
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ads.models import AdDeliveryEvent, AdSlotConfig
from apps.ads.serializers import (
    AdDeliveryEventIngestSerializer,
    AdMetricsSerializer,
    AdSlotConfigSerializer,
)


class AdEventIngestView(APIView):
    def get_permissions(self):
        return [IsAuthenticated()]

    def post(self, request):
        serializer = AdDeliveryEventIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        ad_event_key = payload["ad_event_key"]
        campaign_key = str(payload.get("campaign_key", "")).strip().lower()
        if not campaign_key and "-feed-" in ad_event_key:
            campaign_key = ad_event_key.split("-feed-", 1)[0].strip().lower()
        AdDeliveryEvent.objects.create(
            user_id=request.user.id if request.user.is_authenticated else None,
            event_type=payload["event_type"],
            ad_event_key=ad_event_key,
            campaign_key=campaign_key,
            placement=payload.get("placement", "feed") or "feed",
            region_code=(payload.get("region_code", "global") or "global").lower(),
            metadata=payload.get("metadata", {}),
        )
        return Response({"ingested": True}, status=status.HTTP_201_CREATED)


class AdMetricsView(APIView):
    def get_permissions(self):
        return [IsAuthenticated()]

    def get(self, request):
        events = AdDeliveryEvent.objects.all()
        if request.query_params.get("region"):
            events = events.filter(region_code=request.query_params["region"].strip().lower())
        if request.query_params.get("campaign"):
            events = events.filter(campaign_key=request.query_params["campaign"].strip().lower())
        totals = events.aggregate(
            impressions=Count("id", filter=Q(event_type=AdDeliveryEvent.EventType.IMPRESSION)),
            clicks=Count("id", filter=Q(event_type=AdDeliveryEvent.EventType.CLICK)),
        )
        impressions = int(totals["impressions"] or 0)
        clicks = int(totals["clicks"] or 0)
        by_region_raw = events.values("region_code").annotate(
            impressions=Count("id", filter=Q(event_type=AdDeliveryEvent.EventType.IMPRESSION)),
            clicks=Count("id", filter=Q(event_type=AdDeliveryEvent.EventType.CLICK)),
        )
        by_region = {
            item["region_code"]: {
                "impressions": int(item["impressions"] or 0),
                "clicks": int(item["clicks"] or 0),
            }
            for item in by_region_raw
        }
        by_campaign_raw = events.values("campaign_key").annotate(
            impressions=Count("id", filter=Q(event_type=AdDeliveryEvent.EventType.IMPRESSION)),
            clicks=Count("id", filter=Q(event_type=AdDeliveryEvent.EventType.CLICK)),
        )
        by_campaign = {
            (item["campaign_key"] or "uncategorized"): {
                "impressions": int(item["impressions"] or 0),
                "clicks": int(item["clicks"] or 0),
            }
            for item in by_campaign_raw
        }
        payload = {
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round(clicks / impressions, 4) if impressions else 0.0,
            "by_region": by_region,
            "by_campaign": by_campaign,
        }
        response_serializer = AdMetricsSerializer(payload)
        return Response(response_serializer.data)


class AdSlotConfigListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get(self, request):
        region = str(request.query_params.get("region", "")).strip().lower()
        queryset = AdSlotConfig.objects.order_by("-updated_at")
        if region:
            queryset = queryset.filter(region_code=region)
        serializer = AdSlotConfigSerializer(queryset[:100], many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = AdSlotConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = serializer.save()
        return Response(AdSlotConfigSerializer(config).data, status=status.HTTP_201_CREATED)


class AdSlotConfigDetailView(APIView):
    def get_permissions(self):
        return [IsAdminUser()]

    def patch(self, request, config_id: int):
        config = AdSlotConfig.objects.filter(id=config_id).first()
        if not config:
            return Response({"detail": "Ad config not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdSlotConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(AdSlotConfigSerializer(updated).data)
