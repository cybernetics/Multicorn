# -*- coding: utf-8 -*-
# This file is part of Dyko
# Copyright © 2008-2009 Kozea
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kalamar.  If not, see <http://www.gnu.org/licenses/>.

from .base import AccessPoint
from ..item import Item
from ..property import Property 
from werkzeug import cached_property
from sqlalchemy import sql
from sqlalchemy import Table, Column, MetaData, ForeignKey, create_engine
from sqlalchemy.sql.expression import alias, Select
from sqlalchemy import String,Integer,Date,Numeric,DateTime,Boolean,Unicode
from ..request import Condition, And, Or, Not


SQLALCHEMYTYPES = {
    unicode : Unicode,
    int : Integer
}

class AlchemyProperty(Property):

    def __init__(self, property_type, column_name, identity=False, auto=False,
                 default=None, mandatory=False, relation=None, remote_ap=None,
                 remote_property=None):
        super(AlchemyProperty, self).__init__(property_type, identity, auto, default, mandatory, 
                relation, remote_ap, remote_property)
        self.column_name = column_name



class Alchemy(AccessPoint):

    __metadatas = {}

    def __init__(self, url, tablename, properties, identity_property, createtable=False):
        self.url = url
        self.properties = properties
        self.tablename = tablename
        self.identity_properties = [identity_property]
        self.createtable = createtable
        self.remote_alchemy_props = []


    @cached_property
    def _table(self):
        """ Initialize the sql alchemy engine on first access """
        metadata = Alchemy.__metadatas.get(self.url, None)
        if not metadata:
            engine = create_engine(self.url)
            metadata = MetaData()
            metadata.bind = engine
            Alchemy.__metadatas[self.url] = metadata
        self.metadata = metadata
        columns = []
        for name, prop in self.properties.items():
            alchemy_type = SQLALCHEMYTYPES.get(prop.type,None)
            kwargs = {'key' : name}
            if name in self.identity_properties:
                kwargs['primary_key'] = True
            if prop.default:
                kwargs[default] = prop.default
            if prop.relation == 'many-to-one':
                foreign_ap = self.site.access_points[prop.remote_ap]
                #Transpose the kalamar relation in alchemy if possible
                if isinstance(foreign_ap, Alchemy):
                    foreign_table = foreign_ap.tablename
                    self.remote_alchemy_props.append(name)
                    fk = ForeignKey("%s.%s" % foreign_table,foreign_column)
                    column = Column(prop.column_name, alchemy_type, fk, kwargs)
                    prop.foreign_ap = foreign_ap
                else :
                    foreign_prop = foreign_ap.properties[foreign_ap.identity_properties[0]]
                    alchemy_type = alchemy_type or \
                        SQLALCHEMYTYPES.get(foreign_prop.type, None)
                    column = Column(prop.column_name, alchemy_type, **kwargs)
            elif prop.relation == 'one-to-many':
                pass
            else :
                column = Column(prop.column_name, alchemy_type, **kwargs)
            prop._column = column
            columns.append(column)
        table = Table(self.tablename, metadata, *columns, useexisting=True)
        if self.createtable :
            table.create(checkfirst=True)
        return table
        

    def __get_column(self, propertyname):
        splitted = propertyname.split(".")
        prop = self.properties[splitted[0]]
        if len(splitted) > 1 :
            return prop.foreign_ap.__get_column(propertyname[1:])
        else:
            return prop._column

    def __to_alchemy_condition(self, condition):
        if isinstance(condition, And):
            return apply(sql.and_,[self.__to_alchemy_condition(cond)
                for cond in condition.sub_requests])
        elif isinstance(condition, Or):
            return apply(sql.or_,[self.__to_alchemy_condition(cond)
                for cond in condition.sub_requests])
        elif isinstance(condition, Not):
            return apply(sql.not_,[self.__to_alchemy_condition(cond)
                for cond in condition.sub_requests])
        else:
            col = self.__get_column(condition.property_name)
            if condition.operator == '=':
                return col == condition.value
            else:
                return col.op(condition.operator)(condition.value)
        
    def __item_from_result(self, result):
        lazy_props = {}
        props = {}
        return self.create(dict(result))
                
    def search(self, request):
        query = Select(None, None, from_obj=self._table, use_labels=True)
        query.append_whereclause(self.__to_alchemy_condition(request))
        for name, prop in self.properties.items():
            query.append_column(prop._column.label(name))
        result = query.execute()
        for line in result:
            yield self.__item_from_result(line)

    def __to_pk_where_clause(self, item):
        return self.__to_alchemy_condition(apply(And, [Condition(pk, "=", item[pk]) 
            for pk in self.identity_properties]))
        
    def __transform_to_table(self, item):
        item_dict = {}
        for prop, value in item.items():
            if self.properties[prop].relation == 'many-to-one':
                #TODO: more than one identity property
                item_dict[prop] = item[prop].identity.conditions.values()[0]
            elif self.properties[prop].relation == 'one-to-many':
                pass
            else :
                item_dict[prop] = value
        return item_dict


    def save(self, item):
        conn = self._table.bind.connect()
        trans = conn.begin()
        value = self.__transform_to_table(item)
        try:
            ids = self._table.insert().values(value).execute().inserted_primary_key
            for (id,pk) in zip(ids, self.identity_properties):
                item[pk] = id
            trans.commit()
        except:
            try:
                whereclause = self.__to_pk_where_clause(item)
                update = self._table.update()
                rp = update.where(whereclause).values(value).execute()
                if rp.rowcount == 0:
                    raise
                trans.commit()
            except:
                trans.rollback()
                raise
        finally:
            conn.close()

    def delete(self, item):
        whereclause = self.__to_pk_where_clause(item)
        self._table.delete().where(whereclause).execute()

 
