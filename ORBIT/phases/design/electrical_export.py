__author__ = ["Sophie Bredenkamp"]
__copyright__ = "Copyright 2020, National Renewable Energy Laboratory"
__maintainer__ = ""
__email__ = []

import numpy as np

# from ORBIT.core.library import extract_library_specs
from ORBIT.phases.design import DesignPhase
from ORBIT.phases.design._cables import CableSystem


class ElectricalDesign(DesignPhase, CableSystem):
    """
    Design phase for export cabling and offshore substation systems.
    
    Attributes
    ----------
    num_cables : int
        Total number of cables required for transmitting power.
    length : float
        Length of a single cable connecting the OSS to the interconnection in km.
    mass : float
        Mass of `length` in tonnes.
    cable : `Cable`
        Instance of `ORBIT.phases.design.Cable`. An export system will
        only require a single type of cable.
    total_length : float
        Total length of cable required to trasmit power.
    total_mass : float
        Total mass of cable required to transmit power.
    sections_cables : np.ndarray, shape: (`num_cables, )
        An array of `cable`.
    sections_lengths : np.ndarray, shape: (`num_cables, )
        An array of `length`.
    
    """

    expected_config = {
        "site": {"distance_to_landfall": "km", "depth": "m"},
        "landfall": {"interconnection_distance": "km (optional)"},
        "plant": {"capacity": "MW"},
        "export_system_design": {
            "cables": "str",
            "num_redundant": "int (optional)",
            "touchdown_distance": "m (optional, default: 0)",
            "percent_added_length": "float (optional)",
        },
        "substation_design": {
            "mpt_cost_rate": "USD/MW (optional)",
            "topside_fab_cost_rate": "USD/t (optional)",
            "topside_design_cost": "USD (optional)",
            "shunt_cost_rate": "USD/MW (optional)",
            "switchgear_cost": "USD (optional)",
            "backup_gen_cost": "USD (optional)",
            "workspace_cost": "USD (optional)",
            "other_ancillary_cost": "USD (optional)",
            "topside_assembly_factor": "float (optional)",
            "oss_substructure_cost_rate": "USD/t (optional)",
            "oss_pile_cost_rate": "USD/t (optional)",
            "num_substations": "int (optional)",
        },
    }

    output_config = {
        
        "num_substations": "int",
        "offshore_substation_topside": "dict",
        "offshore_substation_substructure": "dict",
        
        "export_system": {
            "cable": {
                "linear_density": "t/km",
                "sections": [("length, km", "speed, km/h (optional)")],
                "number": "int (optional)",
                "diameter": "int",
            },
        },
    }

    def __init__(self, config, **kwargs):
        """Creates an instance of `TemplateDesign`."""

        config = self.initialize_library(config, **kwargs)
        self.config = self.validate_config(config)

        # CABLES
        super().__init__(config, "export", **kwargs)
        
        for name in self.expected_config["site"]:
            setattr(self, "".join(("_", name)), config["site"][name])
        self._depth = config["site"]["depth"]
        self._distance_to_landfall = config["site"]["distance_to_landfall"]
        self._plant_capacity = self.config["plant"]["capacity"]
        self._get_touchdown_distance()

        try:
            self._distance_to_interconnection = config["landfall"][
                "interconnection_distance"
            ]
        except KeyError:
            self._distance_to_interconnection = 3
            
        # SUBSTATION
        self._outputs = {}

    def run(self):
        """Main run function."""
        
        # CABLES
        self._initialize_cables()
        self.cable = self.cables[[*self.cables][0]]
        self.compute_number_cables()
        self.compute_cable_length()
        self.compute_cable_mass()
        self.compute_total_cable()
        
        for name, cable in self.cables.items():
            self._outputs["export_system"]["cable"] = {
                    "linear_density": cable.linear_density,
                    "sections": [self.length],
                    "number": self.num_cables,
                    "cable_power": cable.cable_power,
                }
        # self._outputs["export_system"] = {
        #     "power_factor": self.cables.power_factor,
        #     "interconnection_distance": self._distance_to_interconnection,
        #     "system_cost": self.total_cost,
        # }
        
        # SUBSTATION
        self.calc_substructure_length()
        self.calc_substructure_deck_space()
        self.calc_topside_deck_space()

        self.calc_num_mpt_and_rating()
        self.calc_mpt_cost()
        self.calc_topside_mass_and_cost()
        self.calc_shunt_reactor_cost()
        self.calc_switchgear_cost()
        self.calc_ancillary_system_cost()
        self.calc_assembly_cost()
        self.calc_substructure_mass_and_cost()

        self._outputs["offshore_substation_substructure"] = {
            "type": "Monopile",  # Substation install only supports monopiles
            "deck_space": self.substructure_deck_space,
            "mass": self.substructure_mass,
            "length": self.substructure_length,
            "unit_cost": self.substructure_cost,
        }

        self._outputs["offshore_substation_topside"] = {
            "deck_space": self.topside_deck_space,
            "mass": self.topside_mass,
            "unit_cost": self.substation_cost,
        }

        self._outputs["num_substations"] = self.num_substations
        

    @property
    def detailed_output(self):
        """Returns export system design outputs."""

        _output = {
            **self.design_result,
            "export_system_total_mass": self.total_mass,
            "export_system_total_length": self.total_length,
            "export_system_total_cost": self.total_cable_cost,
            "export_system_cable_power": self.cable.cable_power,
            "num_substations": self.num_substations,
            "substation_mpt_rating": self.mpt_rating,
            "substation_topside_mass": self.topside_mass,
            "substation_topside_cost": self.topside_cost,
            "substation_substructure_mass": self.substructure_mass,
            "substation_substructure_cost": self.substructure_cost,
        }

        return _output 
    
    @property
    def design_result(self):
        """
        Returns the results of self.run().
        """
        if not self._outputs:
            raise Exception("Has OffshoreSubstationDesign been ran yet?")

        return self._outputs

        #################### CABLES ########################
        
    @property
    def total_cable_cost(self):
        """Returns total array system cable cost."""

        return sum(self.cost_by_type.values())


    def compute_number_cables(self):
        """
        Calculate the total number of required and redundant cables to
        transmit power to the onshore interconnection.
        """

        num_required = np.ceil(self._plant_capacity / self.cable.cable_power)
        num_redundant = self._design.get("num_redundant", 0)

        self.num_cables = int(num_required + num_redundant)

    def compute_cable_length(self):
        """
        Calculates the total distance an export cable must travel.
        """

        added_length = 1.0 + self._design.get("percent_added_length", 0.0)
        self.length = round(
            (
                self.free_cable_length
                + (self._distance_to_landfall - self.touchdown / 1000)
                + self._distance_to_interconnection
            )
            * added_length,
            10,
        )

    def compute_cable_mass(self):
        """
        Calculates the total mass of a single length of export cable.
        """

        self.mass = round(self.length * self.cable.linear_density, 10)

    def compute_total_cable(self):
        """
        Calculates the total length and mass of cables required to fully
        connect the OSS to the interconnection point.
        """

        self.total_length = round(self.num_cables * self.length, 10)
        self.total_mass = round(self.num_cables * self.mass, 10)

    @property
    def sections_cable_lengths(self):
        """
        Creates an array of section lengths to work with `CableSystem`

        Returns
        -------
        np.ndarray
            Array of `length` with shape (`num_cables`, ).
        """
        return np.full(self.num_cables, self.length)

    @property
    def sections_cables(self):
        """
        Creates an array of cable names to work with `CableSystem`.

        Returns
        -------
        np.ndarray
            Array of `cable.name` with shape (`num_cables`, ).
        """

        return np.full(self.num_cables, self.cable.name)

    
    
    
        #################### SUBSTATION ####################
        
        
    def calc_num_substation(self):
        """Computes number of substations"""
        _design = self.config.get("substation_design",{})
        self.num_substations = _design.get(
            "num_substations", int(np.ceil(self._plant_capacity / 800))
        )
            
        
    @property
    def substation_cost(self):
        """Returns total procuremet cost of the topside."""

        return (
            self.mpt_cost
            + self.shunt_reactor_cost
            + self.switchgear_cost
            + self.topside_cost
            + self.ancillary_system_cost
            + self.land_assembly_cost
        )
    
    def calc_mpt_cost(self):
        """Computes transformer cost"""
        num_mpt = self.num_cables
        self.mpt_cost = num_mpt * 1750000
        self.mpt_rating = (
            round(
                (  
                    self._plant_capacity / (num_mpt * self.num_substation)
                )
                /10.0
            ) 
            * 10.0
        )
        
        
    def calc_shunt_reactor_cost(self):
        """Computes shunt reactor cost"""
        # get distance to shore
        compensation = (
            self.export_system_design.touchdown_distance 
            * self.cables.compensation_factor
        )  # MW
        self.shunt_reactor_cost = compensation * 120000
        
    def calc_switchgear_cost(self):
        """Computes switchgear cost"""
        
        num_switchgear = self.num_cables
        self.swtichgear_costs = num_switchgear * 134000
        
    def calc_topside_cost(self):
        """Computes topside cost"""
        self.topside_cost = 1
        
        
    def calc_ancillary_system_cost(self):
        """
        Calculates cost of ancillary systems.

        Parameters
        ----------
        backup_gen_cost : int | float
        workspace_cost : int | float
        other_ancillary_cost : int | float
        """

        _design = self.config.get("substation_design", {})
        backup_gen_cost = _design.get("backup_gen_cost", 1e6)
        workspace_cost = _design.get("workspace_cost", 2e6)
        other_ancillary_cost = _design.get("other_ancillary_cost", 3e6)

        self.ancillary_system_costs = (
            backup_gen_cost + workspace_cost + other_ancillary_cost
        )
        
    def calc_assembly_cost(self):
        """
        Calculates the cost of assembly on land.

        Parameters
        ----------
        topside_assembly_factor : int | float
        """

        _design = self.config.get("substation_design", {})
        topside_assembly_factor = _design.get("topside_assembly_factor", 0.075)
        self.land_assembly_cost = (
            self.switchgear_costs
            + self.shunt_reactor_cost
            + self.ancillary_system_costs
        ) * topside_assembly_factor
        
    def calc_substructure_mass_and_cost(self):
        """
        Calculates the mass and associated cost of the substation substructure.

        Parameters
        ----------
        oss_substructure_cost_rate : int | float
        oss_pile_cost_rate : int | float
        """

        _design = self.config.get("substation_design", {})
        oss_substructure_cost_rate = _design.get(
            "oss_substructure_cost_rate", 3000
        )
        oss_pile_cost_rate = _design.get("oss_pile_cost_rate", 0)

        substructure_mass = 0.4 * self.topside_mass
        substructure_pile_mass = 8 * substructure_mass ** 0.5574
        self.substructure_cost = (
            substructure_mass * oss_substructure_cost_rate
            + substructure_pile_mass * oss_pile_cost_rate
        )

        self.substructure_mass = substructure_mass + substructure_pile_mass    
    
    def calc_substructure_length(self):
        """
        Calculates substructure length as the site depth + 10m
        """

        self.substructure_length = self.config["site"]["depth"] + 10

    def calc_substructure_deck_space(self):
        """
        Calculates required deck space for the substation substructure.

        Coming soon!
        """

        self.substructure_deck_space = 1

    def calc_topside_deck_space(self):
        """
        Calculates required deck space for the substation topside.

        Coming soon!
        """

        self.topside_deck_space = 1
    
    def calc_topside_mass_and_cost(self):
        """
        Calculates the mass and cost of the substation topsides.

        Parameters
        ----------
        topside_fab_cost_rate : int | float
        topside_design_cost: int | float
        """

        _design = self.config.get("substation_design", {})
        topside_fab_cost_rate = _design.get("topside_fab_cost_rate", 14500)
        topside_design_cost = _design.get("topside_design_cost", 4.5e6)

        self.topside_mass = 3.85 * self.mpt_rating * self.num_mpt + 285
        self.topside_cost = (
            self.topside_mass * topside_fab_cost_rate + topside_design_cost
        )

    @property
    def total_oss_cost(self):
        """Returns total cost of subcomponent(s)."""

        num_turbines = 100  # Where applicable
        return self.result * num_turbines

