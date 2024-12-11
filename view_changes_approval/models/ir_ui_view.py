from odoo import api, models, fields, _
from odoo.exceptions import ValidationError, UserError

import logging
import difflib
import re

_logger = logging.getLogger(__name__)

SURROUNDING_LINE = 10
INDENT = "  "  # 2 spaces


def indent_xml(xml):
    indent = 0
    new_xml = []
    xml = xml.splitlines()
    open_tag = re.compile(r'<[a-z]+(?![^>]*\/>)[^>]*>')
    close_tag = re.compile(r'</[a-z0-9]*>')
    for line in xml:
        line = line.strip()
        o_tags = open_tag.findall(line)
        c_tags = close_tag.findall(line)

        if not line:  # empty line
            new_xml.append(line)
        elif line and ((line.startswith("<!--") and line.endswith("-->")) or (not c_tags and not o_tags)):
            # comment line
            new_xml.append(INDENT * indent + line)
        else:
            if c_tags and not o_tags:  # contain only closing tags
                indent -= len(c_tags)
                new_xml.append(INDENT * indent + line)

            elif not c_tags and o_tags:  # contain only opening tags
                new_xml.append(INDENT * indent + line)
                indent += len(o_tags)

            elif c_tags and o_tags:  # contain both opening and closing tags
                if len(c_tags) > len(o_tags):
                    indent -= (len(c_tags) - len(o_tags))
                    new_xml.append(INDENT * indent + line)
                    continue
                elif len(c_tags) < len(o_tags):
                    new_xml.append(INDENT * indent + line)
                    indent += (len(o_tags) - len(c_tags))

    return "\n".join(new_xml)


class View(models.Model):
    _inherit = "ir.ui.view"


    def get_difference_duplicated_view_arch_json(self):
        view = self
        view_key = view.key
        duplicated_view = self.env['ir.ui.view'].search([('key', '=', view_key)]) - view
        if len(duplicated_view) != 1:
            view_name = view.name
            duplicated_view = self.env['ir.ui.view'].search([('name', '=', view_name)]) - view
            if len(duplicated_view) != 1:
                _logger.warning("Not able to find duplicated view with key %s", view_key)
                return

        new_arch = view.arch
        duplicated_arch = duplicated_view.arch

        split_new_arch = new_arch.splitlines()
        split_duplicated_arch = duplicated_arch.splitlines()

        new_arch = [x.strip() for x in split_new_arch]
        duplicated_arch = [x.strip() for x in split_duplicated_arch]

        diff = difflib.unified_diff(duplicated_arch, new_arch, n=0,
                                    fromfile="duplicated view: {} ({})".format(duplicated_view.key, duplicated_view.id),
                                    tofile="code view: {} ({})".format(view.key, view.id))

        differences = []
        difference = {}
        for line in list(diff)[2:]:
            if line.startswith('@@'):
                if difference:
                    difference["add_count"] = len(difference.get("add", []))
                    difference["new_arch"] = (
                        split_new_arch[difference["new_line_number"] - 1:
                                       difference["new_line_number"] + len(difference.get("add", [])) - 1])
                    difference["duplicated_arch"] = (
                        split_duplicated_arch[difference["old_line_number"] - 1:
                                              difference["old_line_number"] + len(difference.get("remove", [])) - 1])
                    difference["remove_count"] = len(difference.get("remove", []))
                    differences.append(difference)
                    difference = {}
                parts = line.split(' ')
                difference["old_line_number"] = int(parts[1].split(',')[0].replace('-', ''))
                difference["new_line_number"] = int(parts[2].split(',')[0].replace('+', ''))
            elif line.startswith('-'):
                difference["remove"] = [line[1:]] if not difference.get("remove") else difference["remove"] + [line[1:]]
            elif line.startswith('+'):
                difference["add"] = [line[1:]] if not difference.get("add") else difference["add"] + [line[1:]]

        if difference:
            difference["add_count"] = len(difference.get("add", []))
            difference["new_arch"] = (
                split_new_arch[difference["new_line_number"] - 1:
                               difference["new_line_number"] + len(difference.get("add", [])) - 1])
            difference["duplicated_arch"] = (
                split_duplicated_arch[difference["old_line_number"] - 1:
                                      difference["old_line_number"] + len(difference.get("remove", [])) - 1])
            difference["remove_count"] = len(difference.get("remove", []))
            differences.append(difference)

        return differences

    def get_difference_duplicated_view_arch(self):
        view = self
        view_key = view.key
        duplicated_view = self.env['ir.ui.view'].search([('key', '=', view_key)]) - view
        if len(duplicated_view) != 1:
            _logger.warning("Not able to find duplicated view with key %s", view_key)
            return

        new_arch = view.arch
        duplicated_arch = duplicated_view.arch

        new_arch = new_arch.splitlines()
        duplicated_arch = duplicated_arch.splitlines()

        new_arch = [x.strip() for x in new_arch]
        duplicated_arch = [x.strip() for x in duplicated_arch]

        diff = difflib.unified_diff(
            duplicated_arch, new_arch, n=0,
            fromfile="duplicated view: {} ({})".format(duplicated_view.key, duplicated_view.id),
            tofile="code view: {} ({})".format(view.key, view.id))

        raise ValidationError("\n".join(diff))


class ReplaceViewWizard(models.TransientModel):
    _name = "replace.view.wizard"
    _description = "Replace in duplicated view"

    updated_duplicated_view = fields.Text()

    def _default_view(self):
        active_id = self.env.context.get("active_id")
        if active_id:
            return self.env["ir.ui.view"].browse(active_id)
        return self.env["ir.ui.view"]

    original_view = fields.Many2one("ir.ui.view", required=True, default=_default_view)
    original_view_id = fields.Integer(related="original_view.id", string="oid")
    duplicated_view = fields.Many2one("ir.ui.view", compute="_compute_duplicated_view", store=True)
    duplicated_view_id = fields.Integer(related="duplicated_view.id", string="did")

    @api.depends("original_view")
    def _compute_duplicated_view(self):
        for wizard in self:
            view_key = wizard.original_view.key
            view_name = wizard.original_view.name
            if not view_key and not view_name:
                wizard.duplicated_view = False
                raise ValidationError(_("Cannot find duplicated view"))
            else:
                duplicated_view_key = self.env['ir.ui.view'].search([('key', '=', view_key)]) - wizard.original_view if view_key else False
                duplicated_view_name = self.env['ir.ui.view'].search([('name', '=', view_name)]) - wizard.original_view if view_name else False
                if not duplicated_view_key and not duplicated_view_name:
                    raise ValidationError("Not able to find duplicated view.")
                elif duplicated_view_key and len(duplicated_view_key) == 1:
                    duplicated_view = duplicated_view_key
                elif not duplicated_view_key and len(duplicated_view_name) == 1:
                    duplicated_view = duplicated_view_name
                else:
                    raise ValidationError("Too much duplicated views found")

                wizard.duplicated_view = duplicated_view
                wizard.changes = wizard.original_view.get_difference_duplicated_view_arch_json()
                if not wizard.changes:
                    raise ValidationError(_("Duplicated view does not have any differences."))
                wizard._compute_progression()
                wizard._compute_new_old_change()
                wizard._compute_before_after_change()

    changes = fields.Json(compute="_compute_duplicated_view", store=True)
    change_id = fields.Integer(default=0)
    changes_approved = fields.Json(default=[])

    actual_new_change_original = fields.Text(compute="_compute_new_old_change")
    actual_old_change_original = fields.Text(compute="_compute_new_old_change")

    manual_change = fields.Text()
    progression = fields.Char(compute="_compute_progression")

    is_review_complete = fields.Boolean(compute="_compute_is_review_complete")

    before_change_x_lines = fields.Text(compute="_compute_before_after_change")
    after_change_x_lines = fields.Text(compute="_compute_before_after_change")

    def _compute_before_after_change(self):
        """
        Compute context along the changes
        """
        dup_arch = self.duplicated_view.arch.splitlines()

        if self.change_id >= len(self.changes):
            self.before_change_x_lines = self.after_change_x_lines = False
            return
        change = self.changes[self.change_id]
        if change.get("remove_count"):  # replace/remove case
            before_change = self._apply_changes_on_arch(dup_arch[:change["old_line_number"] - 1]).splitlines()
            after_change = dup_arch[change["old_line_number"] - 1 + change["remove_count"]:]

        else:  # add case
            before_change = self._apply_changes_on_arch(dup_arch[:change["old_line_number"]]).splitlines()
            after_change = dup_arch[change["old_line_number"]:]

        self.before_change_x_lines = "\n".join(
            before_change[max(len(before_change) - SURROUNDING_LINE, 0):])
        self.after_change_x_lines = "\n".join(after_change[:SURROUNDING_LINE])

    def _compute_is_review_complete(self):
        for w in self:
            w.is_review_complete = w.change_id >= len(w.changes) if w.changes else False

    def _compute_progression(self):
        for w in self:
            if w.changes:
                w.progression = "{} / {}".format(w.change_id+1, len(w.changes))
            else:
                w.progression = "0 / 0"

    def _compute_new_old_change(self):
        """
        Compute the actual change (add and remove)
        """
        for w in self:
            if w.changes and w.change_id < len(w.changes):
                w.actual_old_change_original = (
                    "\n".join(w.changes[w.change_id]["duplicated_arch"])
                    if w.changes[w.change_id].get("duplicated_arch") else False)
                w.actual_new_change_original = (
                    "\n".join(w.changes[w.change_id]["new_arch"])
                    if w.changes[w.change_id].get("new_arch") else False)
            else:
                w.actual_old_change_original = False
                w.actual_new_change_original = False
            if not w.manual_change:
                w.manual_change = w.actual_new_change_original
                w.manual_change = w.actual_new_change_original

    def approve_change(self):
        """
        Save changes in field "changes_approved" once approved
        Then go to next change.
        """
        self.ensure_one()
        changes = self.changes[self.change_id].copy()
        if self.manual_change:
            changes["add"] = self.manual_change.split("\n")

        if self.changes_approved:
            self.changes_approved = self.changes_approved + [changes]
        else:
            self.changes_approved = [changes]
        self.change_id += 1
        self.manual_change = False
        return self._reopen_wizard()

    def skip_change(self):
        """
        Go to next change.
        """
        self.ensure_one()
        self.change_id += 1
        self.manual_change = False
        return self._reopen_wizard()

    def _apply_changes_on_arch(self, arch_lines):
        """
        Apply approved changes on architecture
        """
        if not self.changes_approved:
            return "\n".join(arch_lines)
        for change in self.changes_approved[::-1]:
            if change.get("remove_count") and change.get("add_count"):  # replace case
                arch_lines = (
                        arch_lines[:change["old_line_number"] - 1]
                        + change["new_arch"]
                        + arch_lines[change["old_line_number"] - 1 + change["remove_count"]:])
            elif change.get("remove_count"):  # remove case
                arch_lines = (
                        arch_lines[:change["old_line_number"] - 1]
                        + arch_lines[change["old_line_number"] - 1 + change["remove_count"]:])
            elif change.get("add_count"):  # add case
                arch_lines = (
                        arch_lines[:change["old_line_number"]]
                        + change["new_arch"]
                        + arch_lines[change["old_line_number"]:])
        return "\n".join(arch_lines)

    def apply_changes(self):
        """
        Apply approved changes on complete architecture.
        """
        if not self.changes_approved:
            raise UserError(_("No change has been approved!"))
        self.updated_duplicated_view = indent_xml(self._apply_changes_on_arch(self.duplicated_view.arch.splitlines()))
        return self._reopen_wizard()

    def replace_in_duplicated_view(self):
        self.duplicated_view.arch = self.updated_duplicated_view

    def reset_manual_change(self):
        self.manual_change = self.actual_new_change_original
        return self._reopen_wizard()

    def _reopen_wizard(self):
        return {
            "name": "Replace in duplicated view",
            "res_model": "replace.view.wizard",
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
