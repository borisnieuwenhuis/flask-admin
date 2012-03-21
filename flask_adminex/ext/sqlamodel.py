from sqlalchemy.orm.properties import RelationshipProperty, ColumnProperty
from sqlalchemy.orm.interfaces import MANYTOONE, ONETOMANY
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.expression import desc

from wtforms.ext.sqlalchemy.orm import model_form, ModelConverter
from wtforms.ext.sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField

from flask import flash

from flask.ext.adminex.model import BaseModelView
from flask.ext.adminex.form import AdminForm


class AdminModelConverter(ModelConverter):
    """
        SQLAlchemy model to form converter
    """
    def __init__(self, view):
        super(AdminModelConverter, self).__init__()

        self.view = view

    def convert(self, model, mapper, prop, field_args):
        if isinstance(prop, RelationshipProperty):
            local_column = prop.local_remote_pairs[0][0]
            remote_model = prop.mapper.class_

            kwargs = {
                'validators': [],
                'filters': [],
                'allow_blank': local_column.nullable,
                'default': None
            }

            if field_args:
                kwargs.update(field_args)

            def query_factory():
                return self.view.session.query(remote_model)

            if prop.direction is MANYTOONE:
                return QuerySelectField(query_factory=query_factory, **kwargs)
            elif prop.direction is ONETOMANY:
                # Skip backrefs
                if not local_column.foreign_keys and self.view.hide_backrefs:
                    return None

                return QuerySelectMultipleField(query_factory=query_factory, **kwargs)
        else:
            # Ignore pk/fk
            if isinstance(prop, ColumnProperty):
                column = prop.columns[0]

                if column.foreign_keys or column.primary_key:
                    return None

            return super(AdminModelConverter, self).convert(model, mapper,
                                                            prop, field_args)


class ModelView(BaseModelView):
    """
        SQLALchemy model view

        Usage sample::

            admin = Admin()
            admin.add_view(ModelView(User, db.session))
    """

    hide_backrefs = True
    """
        Set this to False if you want to see multiselect for model backrefs.
    """

    def __init__(self, model, session,
                 name=None, category=None, endpoint=None, url=None):
        """
            Constructor.

            `model`
                Model class
            `session`
                SQLALchemy session
            `name`
                View name. If not set, will default to model name
            `category`
                Category name
            `endpoint`
                Endpoint name. If not set, will default to model name
            `url`
                Base URL. If not set, will default to '/admin/' + endpoint
        """
        self.session = session

        super(ModelView, self).__init__(model, name, category, endpoint, url)

    # Scaffolding
    def scaffold_list_columns(self):
        """
            Return list of columns from the model.
        """
        columns = []

        mapper = self.model._sa_class_manager.mapper

        for p in mapper.iterate_properties:
            if isinstance(p, RelationshipProperty):
                if p.direction is MANYTOONE:
                    columns.append(p.key)
            elif isinstance(p, ColumnProperty):
                # TODO: Check for multiple columns
                column = p.columns[0]

                if column.foreign_keys or column.primary_key:
                    continue

                columns.append(p.key)

        return columns

    def scaffold_sortable_columns(self):
        """
            Return dictionary of sortable columns.
            Key is column name, value is sort column/field.
        """
        columns = dict()

        mapper = self.model._sa_class_manager.mapper

        for p in mapper.iterate_properties:
            if isinstance(p, ColumnProperty):
                # Sanity check
                if len(p.columns) > 1:
                    raise Exception('Automatic form scaffolding is not supported' +
                                    ' for multi-column properties (%s.%s)' % (self.model.__name__, p.key))

                column = p.columns[0]

                # Can't sort by on primary and foreign keys by default
                if column.foreign_keys or column.primary_key:
                    continue

                columns[p.key] = p.key

        return columns

    def scaffold_form(self):
        """
            Create form from the model.
        """
        return model_form(self.model,
                          AdminForm,
                          self.form_columns,
                          field_args=self.form_args,
                          converter=AdminModelConverter(self))

    # Database-related API
    def get_list(self, page, sort_column, sort_desc, execute=True):
        """
            Return models from the database.

            `page`
                Page number
            `sort_column`
                Sort column name
            `sort_desc`
                Descending or ascending sort
            `execute`
                Execute query immediately? Default is `True`
        """
        query = self.session.query(self.model)

        count = query.count()

        # Sorting
        if sort_column is not None:
            if sort_column in self._sortable_columns:
                sort_field = self._sortable_columns[sort_column]

                # Try to handle it as a string
                if isinstance(sort_field, basestring):
                    # Create automatic join against a table if column name
                    # contains dot.
                    if '.' in sort_field:
                        parts = sort_field.split('.', 1)
                        query = query.join(parts[0])
                elif isinstance(sort_field, InstrumentedAttribute):
                    query = query.join(sort_field.parententity)
                else:
                    sort_field = None

                if sort_field is not None:
                    if sort_desc:
                        query = query.order_by(desc(sort_field))
                    else:
                        query = query.order_by(sort_field)

        # Pagination
        if page is not None:
            query = query.offset(page * self.page_size)

        query = query.limit(self.page_size)

        # Execute if needed
        if execute:
            query = query.all()

        return count, query

    def get_one(self, id):
        """
            Return one model by its id.

            `id`
                Model
        """
        return self.session.query(self.model).get(id)

    # Model handlers
    def create_model(self, form):
        """
            Create model from form.

            `form`
                Form instance
        """
        try:
            model = self.model()
            form.populate_obj(model)
            self.session.add(model)
            self.session.commit()
            return True
        except Exception, ex:
            flash('Failed to create model. ' + str(ex), 'error')
            return False

    def update_model(self, form, model):
        """
            Update model from form.

            `form`
                Form instance
        """
        try:
            form.populate_obj(model)
            self.session.commit()
            return True
        except Exception, ex:
            flash('Failed to update model. ' + str(ex), 'error')
            return False

    def delete_model(self, model):
        """
            Delete model.

            `model`
                Model to delete
        """
        self.session.delete(model)
        self.session.commit()