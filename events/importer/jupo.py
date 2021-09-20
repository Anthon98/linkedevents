# -*- coding: utf-8 -*-
from django.db.models.query_utils import Q
import requests
import logging
import traceback

import rdflib
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django_orghierarchy.models import Organization
from django_orghierarchy.models import OrganizationClass
from rdflib import RDF
from rdflib.namespace import DCTERMS, OWL, SKOS

from events.models import Keyword, KeywordLabel, DataSource, BaseModel, Language

from .util import active_language
from .sync import ModelSyncher
from .base import Importer, register_importer

# Per module logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def rdf_funcs(graph, functype, subj=None, predic=None) -> dict:
    ''' Ease of access RDFLib function iterator. 
    Expandable specifically for LinkedEvents usecase. '''

    result = {'fi': None, 'sv': None, 'en': None}
    if functype == 'objects':
        for obj in graph.objects(subject=subj, predicate=predic):
            result.update(dict({str(obj.language): str(obj.value)}))

    return result


@register_importer
class NewJupoImporter(Importer):
    name = "jupo"
    supported_languages = ['fi', 'sv', 'en']


    def setup(self) -> None:
        # Creating the YSO, JUPO and the Public DataSource for Organizations model.
        data_source_info = {
            'yso': 'Yleinen suomalainen ontologia',
            'jupo': 'Julkisen hallinnon palveluontologia',
            'org': 'Ulkoa tuodut organisaatiotiedot'
            }

        for ds_data in data_source_info:
            try:
                ds = DataSource()
                ds.id = ds_data
                ds.name = data_source_info[ds_data]
                ds.user_editable = True
                ds.save()
            except Exception as e:
                logger.error(e)

        self.data_source = DataSource.objects.get(id='yso')
        self.data_source_jupo = DataSource.objects.get(id='jupo')
        self.data_source_org = DataSource.objects.get(id='org')

        # Creating the Public organizations class for all instances (includes Turku specific organization class).
        try:
            org_class = OrganizationClass()
            org_class.id = 'org:13'
            org_class.name = 'Sanasto'
            org_class.created_time = BaseModel.now()
            org_class.data_source_id = self.data_source_org
            org_class.origin_id = '13'
            org_class.save()
        except Exception as e:
            logger.error(e)

        self.organization_class_13 = OrganizationClass.objects.get(id='org:13')
        
        # Creating YSO & JUPO organizations for keywords.
        organization_info = {
            'yso': {
                'id': 'yso:1200',
                'origin_id': '1200',
                'name': 'YSO',
                'classification_id': 'org:13',
                'data_source': self.data_source
                },
            'jupo': {
                'id': 'jupo:1300',
                'origin_id': '1300',
                'name': 'JUPO',
                'classification_id': 'org:13',
                'data_source': self.data_source_jupo
                }
        }

        for org_data in organization_info:
            try:
                orid = organization_info[org_data]
                org = Organization()
                org.id = orid['id']
                org.origin_id = orid['origin_id']
                org.name = orid['name']
                org.created_time = BaseModel.now()
                org.classification_id = orid['classification_id']
                org.data_source_id = orid['data_source']
                org.save()
            except Exception as e:
                logger.error(e)
        
        self.organization = Organization.objects.get(id='yso:1200')
        self.organization_jupo = Organization.objects.get(id='jupo:1300')

        self.handle()


    def fetch_graph(self) -> dict:
        # Generate graph base, and parse the file.
        graph = rdflib.Graph()
        graph.parse('http://finto.fi/rest/v1/jupo/data')
        return graph


    def process_graph(self, graph) -> dict:
        processed = {}
        for subj_uriRef in graph.subjects(predicate=None, object=SKOS.Concept):
            subj_type, subj_id = subj_uriRef.split('/')[-2:]
            if subj_type in ('jupo', 'yso'):
                formatted_onto = "%s:%s" % (subj_type, subj_id)
                
                # Gather labels: altLabel, prefLabel.
                altLabel = rdf_funcs(graph, "objects", subj_uriRef, SKOS.altLabel)
                prefLabel = rdf_funcs(graph, "objects", subj_uriRef, SKOS.prefLabel)
                
                # Some might be deprecated but have no replacement.
                deprecated = dict({'deprecated': [False, None]})

                if (subj_uriRef, OWL.deprecated, None) in graph:
                    deprecated['deprecated'][0] = True
                    for subj_uriRef, _, object in graph.triples((subj_uriRef, DCTERMS.isReplacedBy, None)):
                        subj_type, subj_id = subj_uriRef.split('/')[-2:]
                        formatted_obj = "%s:%s" % (subj_type, subj_id)
                        deprecated['deprecated'][1] = formatted_obj
                        break

                processed.update(dict({formatted_onto: [altLabel, prefLabel, subj_type, subj_id, deprecated]}))

        return processed


    def save_alt_keywords(self, graph) -> None:
        for value in graph:
            for lang in graph[value][0]:
                if graph[value][0][lang]:
                    try:
                        # Check duplicates:
                        alt_label_exists = KeywordLabel.objects.filter(name=graph[value][0][lang]).exists()
                        if not alt_label_exists:
                            language = Language.objects.get(id=lang)
                            label_object = KeywordLabel(
                                name=graph[value][0][lang], language=language)
                            label_object.save()
                    except Exception as e:
                        logger.error(e)


    def save_keywords(self, graph) -> None:
        try:
            for value in graph:
                keyword = None
                if graph[value][2] == 'jupo':
                    keyword = Keyword(data_source=self.data_source_jupo)
                elif graph[value][2] == 'yso':
                    keyword = Keyword(data_source=self.data_source)
                keyword.id = value
                keyword.created_time = BaseModel.now()
                keyword.name_fi = graph[value][1]['fi']
                keyword.name_sv = graph[value][1]['sv']
                keyword.name_en = graph[value][1]['en']
                keyword.deprecated = graph[value][4]['deprecated'][0]
                keyword.save()

                alts = []
                # Link ManyToMany relation alt label values.
                for alt_lang in graph[value][0]:
                    alt_obj = graph[value][0][alt_lang]
                    cur_obj = KeywordLabel.objects.filter(name=alt_obj, language_id=alt_lang).first()
                    '''
                    An alternative line in case cur_obj does return more than 1 object (clones), but this should never be the case due to
                    duplicate prevention by Django.

                    for obj in objs.iterator():
                        print("here:", type(obj))
                    '''
                    if cur_obj:
                        alts.append(cur_obj)
                
                if alts:
                    keyword.alt_labels.add(*alts)
                    keyword.save()

        except Exception as e:
            logger.error(e)
        
        return graph

 
    def pre_process_kw(self, graph) -> dict:
        ''' pre-process stage checks for data changes. 
            If data has not changed, we remove it from the dict data.'''
        
        to_discard = []
        for formatted_onto in graph:
            try:
                has_val = Keyword.objects.get(id=formatted_onto)
                if has_val:
                    # ID exists, but has deprecated or replacement changed?
                    # Changing words would be fatal and JUPO probably doesn't do this anyway.

                    changed = False

                    if has_val.deprecated != graph[formatted_onto][4]['deprecated'][0] or has_val.replaced_by_id != graph[formatted_onto][4]['deprecated'][1]:
                        changed = True

                    if changed == False:
                        to_discard.append(formatted_onto)

            except ObjectDoesNotExist:
                ''' We don't remove the data. '''
                # print(traceback.format_exc())
        
        for obj in to_discard:
            # Keys that don't change can be discarded after the check:
            # logger.info(("%s Already exists in DB & didn't change, skipping...") % obj)
            graph.pop(obj)
        
        return graph

    
    def map_replacements(self, graph) -> None:
        for value in graph:
            if graph[value][4]['deprecated'][1]:
                try:
                    keyword = Keyword.objects.get(id=value)
                    replaced_keyword = Keyword.objects.get(id=graph[value][4]['deprecated'][1])
                    keyword.replaced_by_id = graph[value][4]['deprecated'][1]
                    keyword.created_time = BaseModel.now()
                    keyword.save()
                    logger.info("Added replacement for: %s" % value)
                except Exception as e:
                    logger.error("Could not find replacement for: %s with error: %s" % (value, e))
                    pass


    def handle(self):
        logger.info("Fetching JUPO data graph file...")
        graph = self.fetch_graph()

        logger.info("Processing graph data...")
        processed_graph = self.process_graph(graph)

        logger.info("Pre-processing keywords...")
        preprocess_kw = self.pre_process_kw(processed_graph)
        
        logger.info("Saving keyword labels (alt labels)...")
        self.save_alt_keywords(preprocess_kw)

        logger.info("Saving keywords...")
        final_graph = self.save_keywords(preprocess_kw)

        logger.info("Mapping replacements...")
        self.map_replacements(final_graph)
