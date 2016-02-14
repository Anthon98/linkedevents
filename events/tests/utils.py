from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory
from rest_framework.settings import api_settings

def assert_event_data_is_equal(d1, d2, version='v1'):
    # TODO: start using version parameter
    # make sure the saved data is equal to the one we posted before
    FIELDS = (
        'data_source',
        'publisher',
        'location',
        'name',
        'event_status',
        'sub_events',
        'custom_data',
        'image',
        'audience',
        'location_extra_info',
        'info_url',
        'description',
        'short_description',
        'provider',
        'keywords',
        'offers',
        'in_language',

        # 'start_time',  # fails because of Javascript's "Z"
        #                # vs Python's "+00:00"
        # 'end_time',    # -"-
    )
    if version == 'v0.1':
        fields += (
            'headline',
            'secondary_headline',
            'origin_id',
        )
    for key in FIELDS:
        if key in d1:
            assert d1[key] == d2[key]

    # test for external links (the API returns OrderedDicts because of the
    # model's unique constraint)
    comp = lambda d: (d['language'], d['link'])
    links1 = set([comp(link) for link in d1.get('external_links', [])])
    links2 = set([comp(link) for link in d2.get('external_links', [])])
    assert links1 == links2


def get(api_client, url):
    response = api_client.get(url, format='json')
    assert response.status_code == 200, str(response.content)
    return response


def assert_fields_exist(data, fields):
    for field in fields:
        assert field in data
    assert len(data) == len(fields)

def versioned_reverse(view, version='v1', **kwargs):
    factory = APIRequestFactory()
    request = factory.options('/')
    request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
    request.version = version
    return reverse(view, request=request, **kwargs)
