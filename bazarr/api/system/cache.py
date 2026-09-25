# coding=utf-8

from flask_restx import Resource, Namespace, reqparse, fields, marshal

from utilities.cache import get_cache_stats, clear_search_results_cache, clear_cache

from ..utils import authenticate

api_ns_system_cache = Namespace('System Cache', description='Show or clear the subtitles cache')


@api_ns_system_cache.route('system/cache')
class SystemCache(Resource):
    get_response_model = api_ns_system_cache.model('SystemCacheGetResponse', {
        'files': fields.Integer(),
        'size': fields.String(),
    })

    @authenticate
    @api_ns_system_cache.response(200, 'Success')
    @api_ns_system_cache.response(401, 'Not Authenticated')
    def get(self):
        """Get the number of files and size of the subtitles cache"""
        return marshal(get_cache_stats(), self.get_response_model, envelope='data')

    delete_request_parser = reqparse.RequestParser()
    delete_request_parser.add_argument('scope', type=str, required=False, default='search',
                                       choices=['search', 'all'],
                                       help='Clear only cached search results (default) or the whole cache')

    @authenticate
    @api_ns_system_cache.doc(parser=delete_request_parser)
    @api_ns_system_cache.response(204, 'Success')
    @api_ns_system_cache.response(401, 'Not Authenticated')
    def delete(self):
        """Clear cached search results or the whole subtitles cache"""
        args = self.delete_request_parser.parse_args()
        if args.get('scope') == 'all':
            clear_cache()
        else:
            clear_search_results_cache()
        return '', 204
