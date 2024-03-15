import time
from typing import List, Tuple

import numpy as np
from cim_optimizer.solve_Ising import *
from simuq import QSystem, Qubit
from simuq.dwave import DWaveProvider

from qhdopt.backend.backend import Backend
from qhdopt.utils.decoding_utils import spin_to_bitstring


class CIMBackend(Backend):
    """
    Backend implementation for CIM-Optimizer. Find more information about CIM-Optimizer
    here: https://cim-optimizer.readthedocs.io/en/latest/
    """

    def __init__(
        self,
        resolution,
        dimension,
        univariate_dict,
        bivariate_dict,
        shots=100,
        embedding_scheme="unary",
        anneal_schedule=None,
        penalty_coefficient=0,
        penalty_ratio=0.75,
        chain_strength_ratio=1.05,
    ):
        super().__init__(
            resolution,
            dimension,
            shots,
            embedding_scheme,
            univariate_dict,
            bivariate_dict,
        )
        if anneal_schedule is None:
            anneal_schedule = [[0, 0], [20, 1]]
        self.anneal_schedule = anneal_schedule
        self.penalty_coefficient = penalty_coefficient
        self.penalty_ratio = penalty_ratio
        self.chain_strength_ratio = chain_strength_ratio
        self.api_key = ""  # CIM backend does not require an API key to run

    def calc_penalty_coefficient_and_chain_strength(self) -> Tuple[float, float]:
        """
        Calculates the penalty coefficient and chain strength using self.penalty_ratio.
        """
        if self.penalty_coefficient != 0:
            chain_strength = np.max(
                [5e-2, self.chain_strength_ratio * self.penalty_coefficient]
            )
            return self.penalty_coefficient, chain_strength

        qs = QSystem()
        qubits = [Qubit(qs) for _ in range(len(self.qubits))]
        qs.add_evolution(
            self.S_x(qubits)
            + self.H_p(qubits, self.univariate_dict, self.bivariate_dict),
            1,
        )
        dwp = DWaveProvider(self.api_key)
        h, J = dwp.compile(qs, self.anneal_schedule)
        max_strength = np.max(np.abs(list(h) + list(J.values())))
        penalty_coefficient = (
            self.penalty_ratio * max_strength if self.embedding_scheme == "unary" else 0
        )
        # chain_strength = np.max([5e-2, 0.5 * self.penalty_ratio])
        chain_strength_multiplier = np.max([1, self.penalty_ratio])
        chain_strength = np.max([5e-2, chain_strength_multiplier * max_strength])
        return penalty_coefficient, chain_strength

    def compile(self, info):
        penalty_coefficient, chain_strength = (
            self.calc_penalty_coefficient_and_chain_strength()
        )
        self.penalty_coefficient, self.chain_strength = (
            penalty_coefficient,
            chain_strength,
        )
        self.qs.add_evolution(
            self.H_p(self.qubits, self.univariate_dict, self.bivariate_dict)
            + penalty_coefficient * self.H_pen(self.qubits),
            1,
        )

        self.dwp = DWaveProvider(self.api_key)
        start_compile_time = time.time()
        self.h, self.J = self.dwp.compile(self.qs, self.anneal_schedule, chain_strength)
        J_array = np.zeros((len(self.qubits), len(self.qubits)))
        for key in self.J:
            J_array[key[0], key[1]] = self.J[key]
        J_array = J_array + J_array.T
        self.J = J_array
        self.h = np.array(self.h)
        end_compile_time = time.time()
        info["compile_time"] = end_compile_time - start_compile_time

    def exec(self, verbose: int, info: dict, compile_only=False) -> List[List[int]]:
        """
        Execute the CIM optimizer using the problem description specified in
        self.univariate_dict and self.bivariate_dict. It uses self.H_p to generate
        the problem hamiltonian and then uses CIM's classical solver.

        Args:
            verbose: Verbosity level.
            info: Dictionary to store information about the execution.
            compile_only: If True, the function only compiles the problem and does not run it.

        Returns:
            raw_samples: A list of raw samples from the CIM optimizer.
        """
        self.compile(info)

        if verbose > 1:
            self.print_compilation_info()

        if verbose > 1:
            print("Submit Task to D-Wave:")
            print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))

        start_run_time = time.time()
        raw_samples = []
        for _ in range(self.shots):
            solution = Ising(self.J, self.h).solve().result["lowest_energy_spin_config"]
            raw_samples.append(solution)

        info["backend_time"] = time.time() - start_run_time

        raw_samples = [spin_to_bitstring(raw_sample) for raw_sample in raw_samples]

        return raw_samples

    def calc_h_and_J(self) -> Tuple[List, dict]:
        """
        Function for debugging to provide h and J which uniquely specify the problem hamiltonian

        Returns:
            h: List of h values
            J: Dictionary of J values
        """
        (
            penalty_coefficient,
            chain_strength,
        ) = self.calc_penalty_coefficient_and_chain_strength()
        self.qs.add_evolution(
            self.S_x(self.qubits)
            + self.H_p(self.qubits, self.univariate_dict, self.bivariate_dict)
            + penalty_coefficient * self.H_pen(self.qubits),
            1,
        )

        dwp = DWaveProvider(self.api_key)
        return dwp.compile(self.qs, self.anneal_schedule, chain_strength)

    def print_compilation_info(self):
        print("* Compilation information")
        print("Final Hamiltonian:")
        print("(Feature under development; only the Hamiltonian is meaningful here)")
        print(self.qs)
        print(f"Annealing schedule parameter: {self.anneal_schedule}")
        print(f"Penalty coefficient: {self.penalty_coefficient}")
        print(f"Chain strength: {self.chain_strength}")
        print(f"Number of shots: {self.shots}")