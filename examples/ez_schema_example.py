import graphene
import django_filters
from graphene import relay, ObjectType, resolve_only_args, ConnectionField
from graphene.utils.subclass_with_meta import SubclassWithMeta_Meta
from graphene_django.types import DjangoObjectType
from graphene_django.fields import DjangoConnectionField
from graphene_django.filter import DjangoFilterConnectionField
from kemcho.equityinvest.decorators import graphene_auth

from kemcho.equityinvest.models import (
    Fund,
    Deal,
    Buyer,
    Transaction,
)

def public(obj, info):
    return True

def logged_in(obj, info):
    # request level caching
    context = info.context
    if not hasattr(context, 'is_auth'):
        context.is_auth = context.user.is_authenticated()

    return context.is_auth


def is_staff(obj, info):
    return info.context.user.is_staff

class FieldPermissionsMeta(SubclassWithMeta_Meta):
    def __new__(mcl, name, bases, nmspc):
        """ Caches the result of """
        def replaced_fnc(fn):
            def cache_function(cls, *args, **kwargs):
                # Cache results of permission checking functions
                # per object per request

                obj = args[0]
                info = args[1]
                cache_key = '%s%s' % (obj.__class__.__name__, obj.pk)
                context = info.context
                if not hasattr(context, 'permission_cache'):
                    context.permission_cache = {}

                if cache_key in context.permission_cache:
                    result = context.permission_cache[cache_key]
                else:
                    result = fn.__func__(cls, *args, **kwargs)
                    context.permission_cache[cache_key] = result

                return result
            return classmethod(cache_function)

        for attr in nmspc:
            if attr.startswith('check_'):
                nmspc[attr] = replaced_fnc(nmspc[attr])
        return super(FieldPermissionsMeta, mcl).__new__(mcl, name, bases, nmspc)

class FieldPermissions(object):
    """
    Permission checking functions should be classmethods named check_<name>
    to take advantage of caching results on the context
    """
    __metaclass__ = FieldPermissionsMeta


class DealPermissions(FieldPermissions):

    @classmethod
    def check_seller_in_deal(cls, deal, info):
        # TODO
        return False

    @classmethod
    def check_buyer_has_transaction(cls, deal, info):
        user = info.context.user
        return Transaction.objects.filter(deal=deal, buyer__eicontact__user=user)


class FundNode(DjangoObjectType):
    class Meta:
        model = Fund
        filter_fields = ['name', 'id', ]
        interfaces = (relay.Node,)

    @classmethod
    @graphene_auth(['staff', ])
    def get_node(cls, info, id):
        return Fund.objects.get(id=id)

class BuyerNode(DjangoObjectType):

    one_deal = graphene.Field('kemcho.equityinvest.schema.DealNode')
    many_deals = DjangoConnectionField('kemcho.equityinvest.schema.DealNode')

    class Meta:
        model = Buyer
        interfaces = (relay.Node,)
        filter_fields = {
            'investment_entity': ['exact', 'icontains', 'istartswith'],
        }

    @staticmethod
    def resolve_one_deal(obj, info, **kwargs):
        return Deal.objects.first()

    @staticmethod
    def resolve_many_deals(obj, info, **kwargs):
        return Deal.objects.filter(share_price=26)


    @classmethod
    @graphene_auth(['staff', 'self' ])
    def get_node(cls, info, id):
        return Buyer.objects.get(id=id)

class DealNode(DjangoObjectType):
    name = graphene.String()
    deal_value = graphene.Float()
    # We can't do a filter field because buyers_without_transaction returns a list
    buyers_without_transaction = DjangoConnectionField(BuyerNode)
    waitlist_buyers = DjangoFilterConnectionField(BuyerNode)

    class Meta:
        model = Deal
        interfaces = (relay.Node,)

    auth = {
        # In Deal
        'id': [public],
        'share_price': [logged_in],
        'name': [DealPermissions.check_seller_in_deal],
        'deal_value': [DealPermissions.check_seller_in_deal],
        'buyers_without_transaction': [public],
        'waitlist_buyers': [public],
    }

    @classmethod
    @graphene_auth([is_staff, DealPermissions.check_seller_in_deal])
    def get_node(cls, info, id):
        return Deal.objects.get(id=id)

    @staticmethod
    def resolve_share_price(obj, info, **kwargs):
        share_price = obj.share_price
        return share_price

    @staticmethod
    def resolve_buyers_without_transaction(obj, info, **kwargs):
        return obj.buyers_without_transaction()

    @staticmethod
    def resolve_waitlist_buyers(obj, info, **kwargs):
        return obj.waitlist_buyers().filter()

class DealFilter(django_filters.FilterSet):

    class Meta:
        model = Deal
        fields = {
            'deal_name_internal': ['exact', 'icontains', 'istartswith'],
            'id': ['exact', 'icontains'],
            'offering_status': ['exact'],
            'inv_opps__company__name': ['exact', 'icontains'],
        }

    @property
    def qs(self):
        # The query context can be found in self.request.
        return super(DealFilter, self).qs.filter(share_price=26)

class CreateFund(relay.ClientIDMutation):
    class Input:
        name = graphene.String(required=True)
        ein = graphene.String(required=True)

    fund = graphene.Field(FundNode)

    @classmethod
    @graphene_auth(['staff', ])
    def mutate_and_get_payload(cls, root, info, **input):
        fund = Fund.objects.create(
            **input
        )
        return CreateFund(fund=fund)


class Query(object):
    node = relay.Node.Field()

    deal = relay.Node.Field(DealNode)
    buyer = relay.Node.Field(BuyerNode)

    funds = DjangoFilterConnectionField(FundNode)
    deals = DjangoFilterConnectionField(DealNode, filterset_class=DealFilter)


class Mutation(graphene.ObjectType):
    create_fund = CreateFund.Field()
